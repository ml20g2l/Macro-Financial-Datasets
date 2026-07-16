-- Reconcile PostgreSQL mart outputs against the verified Python CSV outputs.
-- Run from the repository root after sql/04_validation.sql.

CREATE TEMP TABLE python_regime_asset_metrics (
    regime text,
    ticker text,
    observations bigint,
    annualized_return double precision,
    annualized_volatility double precision,
    max_drawdown double precision,
    sharpe_ratio_rf0 double precision,
    win_rate double precision,
    conditional_cumulative_return double precision
);

\copy python_regime_asset_metrics FROM 'data/processed/regime_asset_metrics.csv' WITH (FORMAT csv, HEADER true);

CREATE TEMP TABLE python_regime_correlations (
    regime text,
    asset_1 text,
    asset_2 text,
    observations bigint,
    correlation double precision
);

\copy python_regime_correlations FROM 'data/processed/regime_correlations.csv' WITH (FORMAT csv, HEADER true);

CREATE TEMP TABLE metric_discrepancies AS
SELECT coalesce(sql.regime, python.regime) AS regime,
       coalesce(sql.ticker, python.ticker) AS ticker,
       sql.observations AS sql_observations,
       python.observations AS python_observations,
       sql.annualized_return AS sql_annualized_return,
       python.annualized_return AS python_annualized_return,
       sql.annualized_volatility AS sql_annualized_volatility,
       python.annualized_volatility AS python_annualized_volatility,
       sql.max_drawdown AS sql_max_drawdown,
       python.max_drawdown AS python_max_drawdown,
       sql.sharpe_ratio_rf0 AS sql_sharpe_ratio_rf0,
       python.sharpe_ratio_rf0 AS python_sharpe_ratio_rf0,
       sql.win_rate AS sql_win_rate,
       python.win_rate AS python_win_rate,
       sql.conditional_cumulative_return AS sql_conditional_cumulative_return,
       python.conditional_cumulative_return AS python_conditional_cumulative_return
FROM mart.regime_asset_metrics AS sql
FULL OUTER JOIN python_regime_asset_metrics AS python USING (regime, ticker)
WHERE sql.regime IS NULL OR python.regime IS NULL
   OR sql.observations <> python.observations
   OR abs(sql.annualized_return - python.annualized_return) > 1e-10
   OR abs(sql.annualized_volatility - python.annualized_volatility) > 1e-10
   OR abs(sql.max_drawdown - python.max_drawdown) > 1e-10
   OR abs(sql.sharpe_ratio_rf0 - python.sharpe_ratio_rf0) > 1e-10
   OR abs(sql.win_rate - python.win_rate) > 1e-10
   OR abs(sql.conditional_cumulative_return - python.conditional_cumulative_return) > 1e-10;

CREATE TEMP TABLE correlation_discrepancies AS
SELECT coalesce(sql.regime, python.regime) AS regime,
       coalesce(sql.asset_1, python.asset_1) AS asset_1,
       coalesce(sql.asset_2, python.asset_2) AS asset_2,
       sql.observations AS sql_observations,
       python.observations AS python_observations,
       sql.correlation AS sql_correlation,
       python.correlation AS python_correlation
FROM mart.regime_correlations AS sql
FULL OUTER JOIN python_regime_correlations AS python
  USING (regime, asset_1, asset_2)
WHERE sql.regime IS NULL OR python.regime IS NULL
   OR sql.observations <> python.observations
   OR abs(sql.correlation - python.correlation) > 1e-10;

TABLE metric_discrepancies;
TABLE correlation_discrepancies;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM metric_discrepancies) THEN
        RAISE EXCEPTION 'PostgreSQL/Python metric discrepancies found';
    END IF;
    IF EXISTS (SELECT 1 FROM correlation_discrepancies) THEN
        RAISE EXCEPTION 'PostgreSQL/Python correlation discrepancies found';
    END IF;
END $$;

SELECT 'metric_discrepancies' AS check_name, count(*) AS discrepancy_rows
FROM metric_discrepancies
UNION ALL
SELECT 'correlation_discrepancies', count(*)
FROM correlation_discrepancies;
