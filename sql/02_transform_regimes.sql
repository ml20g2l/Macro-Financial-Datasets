-- Deterministic staging, one-day-lagged regime classification, and analytics marts.
-- Thresholds match src/build_analysis.py and are not fitted to asset returns.

\set ON_ERROR_STOP on

DROP TABLE IF EXISTS stg.asset_prices CASCADE;
CREATE TABLE stg.asset_prices AS
SELECT DISTINCT ON (to_date(date_text, 'YYYY-MM-DD'), upper(trim(ticker)))
       to_date(date_text, 'YYYY-MM-DD') AS date,
       upper(trim(ticker))              AS ticker,
       close_price_text::numeric        AS close_price
FROM raw.asset_prices
WHERE date_text ~ '^\d{4}-\d{2}-\d{2}$'
  AND upper(trim(ticker)) IN ('SPY', 'IEF', 'GLD')
  AND close_price_text ~ '^[0-9]+(\.[0-9]+)?$'
  AND close_price_text::numeric > 0
ORDER BY to_date(date_text, 'YYYY-MM-DD'), upper(trim(ticker));

ALTER TABLE stg.asset_prices ADD PRIMARY KEY (date, ticker);

DROP TABLE IF EXISTS stg.fred_vix CASCADE;
CREATE TABLE stg.fred_vix AS
SELECT to_date(date_text, 'YYYY-MM-DD') AS date,
       NULLIF(trim(vix_text), '')::double precision AS vix
FROM raw.fred_vix
WHERE date_text ~ '^\d{4}-\d{2}-\d{2}$';
CREATE UNIQUE INDEX stg_fred_vix_date_idx ON stg.fred_vix(date);

DROP TABLE IF EXISTS stg.fred_dgs10 CASCADE;
CREATE TABLE stg.fred_dgs10 AS
SELECT to_date(date_text, 'YYYY-MM-DD') AS date,
       NULLIF(trim(dgs10_text), '')::double precision AS dgs10
FROM raw.fred_dgs10
WHERE date_text ~ '^\d{4}-\d{2}-\d{2}$';
CREATE UNIQUE INDEX stg_fred_dgs10_date_idx ON stg.fred_dgs10(date);

DROP TABLE IF EXISTS stg.boe_bank_rate CASCADE;
CREATE TABLE stg.boe_bank_rate AS
SELECT to_date(effective_date_text, 'DD Mon YY') AS effective_date,
       NULLIF(trim(bank_rate_text), '')::numeric AS bank_rate
FROM raw.boe_bank_rate
WHERE NULLIF(trim(effective_date_text), '') IS NOT NULL;
CREATE UNIQUE INDEX stg_boe_bank_rate_date_idx ON stg.boe_bank_rate(effective_date);

DROP TABLE IF EXISTS stg.daily_macro_aligned CASCADE;
CREATE TABLE stg.daily_macro_aligned AS
WITH asset_calendar AS (
    -- Match Python's inner join across SPY, IEF, and GLD. A date is eligible
    -- only when all three adjusted closing prices are present.
    SELECT date
    FROM stg.asset_prices
    GROUP BY date
    HAVING count(DISTINCT ticker) = 3
), macro_calendar AS (
    -- Reproduce pandas merge_asof on the outer-merged FRED calendar. The most
    -- recent release-calendar row is selected first; a null value on that row
    -- is not silently replaced with an older observation from only one series.
    SELECT coalesce(vix.date, yield_10y.date) AS date,
           vix.vix,
           yield_10y.dgs10
    FROM stg.fred_vix AS vix
    FULL OUTER JOIN stg.fred_dgs10 AS yield_10y USING (date)
)
SELECT calendar.date,
       macro.vix,
       macro.dgs10
FROM asset_calendar AS calendar
LEFT JOIN LATERAL (
    SELECT source.vix, source.dgs10
    FROM macro_calendar AS source
    WHERE source.date <= calendar.date
      AND calendar.date - source.date <= 7
    ORDER BY source.date DESC
    LIMIT 1
) AS macro ON true
ORDER BY calendar.date;
ALTER TABLE stg.daily_macro_aligned ADD PRIMARY KEY (date);

DROP TABLE IF EXISTS mart.daily_macro_regimes CASCADE;
CREATE TABLE mart.daily_macro_regimes AS
WITH features AS (
    SELECT date,
           vix,
           dgs10,
           dgs10 - lag(dgs10, 63) OVER (ORDER BY date) AS dgs10_change_63d_pp
    FROM stg.daily_macro_aligned
), lagged_signals AS (
    SELECT *,
           lag(vix, 1) OVER (ORDER BY date) AS signal_vix,
           lag(dgs10, 1) OVER (ORDER BY date) AS signal_dgs10,
           lag(dgs10_change_63d_pp, 1) OVER (ORDER BY date) AS signal_dgs10_change_63d_pp
    FROM features
), classified AS (
    SELECT *,
           CASE
               WHEN signal_vix IS NULL OR signal_dgs10 IS NULL
                    OR signal_dgs10_change_63d_pp IS NULL THEN 'Unclassified'
               WHEN signal_vix >= 30 THEN 'Stress'
               WHEN signal_vix >= 20 AND signal_vix < 30 THEN 'Elevated risk'
               WHEN signal_vix < 20 AND signal_dgs10_change_63d_pp >= 0.50 THEN 'Tightening'
               WHEN signal_vix < 20 AND signal_dgs10_change_63d_pp < 0.50 THEN 'Calm / easing'
               ELSE 'Unclassified'
           END AS regime
    FROM lagged_signals
), classified_boundaries AS (
    -- Python assigns episodes after removing Unclassified rows, so a missing
    -- macro-signal date does not automatically split an otherwise unchanged
    -- regime episode.
    SELECT date,
           CASE
               WHEN lag(regime) OVER (ORDER BY date) IS DISTINCT FROM regime THEN 1
               ELSE 0
           END AS new_episode
    FROM classified
    WHERE regime <> 'Unclassified'
), boundaries AS (
    SELECT classified.*, classified_boundaries.new_episode
    FROM classified
    LEFT JOIN classified_boundaries USING (date)
)
SELECT date, vix, dgs10, dgs10_change_63d_pp,
       signal_vix, signal_dgs10, signal_dgs10_change_63d_pp, regime,
       CASE WHEN regime = 'Unclassified' THEN NULL
            ELSE sum(coalesce(new_episode, 0)) OVER (ORDER BY date)
       END::bigint AS episode_id
FROM boundaries
ORDER BY date;
ALTER TABLE mart.daily_macro_regimes ADD PRIMARY KEY (date);

DROP TABLE IF EXISTS stg.asset_returns CASCADE;
CREATE TABLE stg.asset_returns AS
SELECT date,
       ticker,
       close_price,
       close_price / lag(close_price) OVER (PARTITION BY ticker ORDER BY date) - 1 AS daily_return
FROM stg.asset_prices;
ALTER TABLE stg.asset_returns ADD PRIMARY KEY (date, ticker);

DROP TABLE IF EXISTS mart.daily_asset_regime_returns CASCADE;
CREATE TABLE mart.daily_asset_regime_returns AS
SELECT returns.date,
       returns.ticker,
       returns.close_price,
       returns.daily_return,
       macro.vix,
       macro.dgs10,
       macro.dgs10_change_63d_pp,
       macro.signal_vix,
       macro.signal_dgs10,
       macro.signal_dgs10_change_63d_pp,
       macro.regime,
       macro.episode_id
FROM stg.asset_returns AS returns
JOIN mart.daily_macro_regimes AS macro USING (date);
ALTER TABLE mart.daily_asset_regime_returns ADD PRIMARY KEY (date, ticker);

DROP TABLE IF EXISTS mart.regime_asset_metrics CASCADE;
CREATE TABLE mart.regime_asset_metrics AS
WITH eligible AS (
    SELECT *
    FROM mart.daily_asset_regime_returns
    WHERE regime <> 'Unclassified'
      AND daily_return IS NOT NULL
      AND daily_return > -1
), aggregate_metrics AS (
    SELECT regime,
           ticker,
           count(*) AS observations,
           avg(daily_return) * 252 AS annualized_return,
           stddev_samp(daily_return) * sqrt(252) AS annualized_volatility,
           (avg(daily_return) * 252)
               / nullif(stddev_samp(daily_return) * sqrt(252), 0) AS sharpe_ratio_rf0,
           avg((daily_return > 0)::int::numeric) AS win_rate,
           exp(sum(ln(1 + daily_return))) - 1 AS conditional_cumulative_return
    FROM eligible
    GROUP BY regime, ticker
), episode_wealth AS (
    SELECT regime,
           ticker,
           episode_id,
           date,
           exp(sum(ln(1 + daily_return)) OVER (
               PARTITION BY ticker, episode_id ORDER BY date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           )) AS wealth
    FROM eligible
), episode_drawdowns AS (
    SELECT *,
           wealth / greatest(
               1,
               max(wealth) OVER (
                   PARTITION BY ticker, episode_id ORDER BY date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               )
           ) - 1 AS drawdown
    FROM episode_wealth
), maximum_drawdowns AS (
    SELECT regime, ticker, least(0, min(drawdown)) AS max_drawdown
    FROM episode_drawdowns
    GROUP BY regime, ticker
)
SELECT aggregate_metrics.regime,
       aggregate_metrics.ticker,
       aggregate_metrics.observations,
       aggregate_metrics.annualized_return,
       aggregate_metrics.annualized_volatility,
       maximum_drawdowns.max_drawdown,
       aggregate_metrics.sharpe_ratio_rf0,
       aggregate_metrics.win_rate,
       aggregate_metrics.conditional_cumulative_return
FROM aggregate_metrics
JOIN maximum_drawdowns USING (regime, ticker);

DROP TABLE IF EXISTS mart.regime_correlations CASCADE;
CREATE TABLE mart.regime_correlations AS
WITH pivoted AS (
    SELECT date,
           regime,
           max(daily_return) FILTER (WHERE ticker = 'SPY') AS spy_return,
           max(daily_return) FILTER (WHERE ticker = 'IEF') AS ief_return,
           max(daily_return) FILTER (WHERE ticker = 'GLD') AS gld_return
    FROM mart.daily_asset_regime_returns
    WHERE regime <> 'Unclassified'
    GROUP BY date, regime
), pairs AS (
    SELECT regime, 'SPY'::text AS asset_1, 'IEF'::text AS asset_2,
           count(*) FILTER (WHERE spy_return IS NOT NULL AND ief_return IS NOT NULL) AS observations,
           corr(spy_return, ief_return) AS correlation
    FROM pivoted GROUP BY regime
    UNION ALL
    SELECT regime, 'SPY', 'GLD',
           count(*) FILTER (WHERE spy_return IS NOT NULL AND gld_return IS NOT NULL),
           corr(spy_return, gld_return)
    FROM pivoted GROUP BY regime
    UNION ALL
    SELECT regime, 'IEF', 'GLD',
           count(*) FILTER (WHERE ief_return IS NOT NULL AND gld_return IS NOT NULL),
           corr(ief_return, gld_return)
    FROM pivoted GROUP BY regime
)
SELECT * FROM pairs;
