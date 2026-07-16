-- Portfolio-facing queries. Values should reconcile with data/processed/*.csv.

-- 1) Exact regime definition and observed class balance.
SELECT regime,
       count(*) AS trading_days,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS share_of_classified_days_pct,
       min(date) AS first_date,
       max(date) AS last_date,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY signal_vix)::numeric, 2) AS median_signal_vix,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY signal_dgs10_change_63d_pp)::numeric, 2)
           AS median_signal_yield_change_pp
FROM mart.daily_macro_regimes
WHERE regime <> 'Unclassified'
GROUP BY regime
ORDER BY CASE regime
    WHEN 'Calm / easing' THEN 1
    WHEN 'Tightening' THEN 2
    WHEN 'Elevated risk' THEN 3
    WHEN 'Stress' THEN 4
END;

-- 2) Return and risk metrics by regime and asset.
SELECT regime,
       ticker,
       observations,
       round((100 * annualized_return)::numeric, 1) AS annualized_return_pct,
       round((100 * annualized_volatility)::numeric, 1) AS annualized_volatility_pct,
       round((100 * max_drawdown)::numeric, 1) AS max_drawdown_pct,
       round(sharpe_ratio_rf0::numeric, 2) AS sharpe_ratio_rf0
FROM mart.regime_asset_metrics
ORDER BY CASE regime
    WHEN 'Calm / easing' THEN 1
    WHEN 'Tightening' THEN 2
    WHEN 'Elevated risk' THEN 3
    WHEN 'Stress' THEN 4
END, ticker;

-- 3) Same-day conditional return correlations.
SELECT regime, asset_1, asset_2, observations, round(correlation::numeric, 2) AS correlation
FROM mart.regime_correlations
ORDER BY regime, asset_1, asset_2;

-- 4) Longest contiguous episodes for boundary-case review.
SELECT regime,
       episode_id,
       min(date) AS start_date,
       max(date) AS end_date,
       count(*) AS trading_days
FROM mart.daily_macro_regimes
WHERE regime <> 'Unclassified'
GROUP BY regime, episode_id
ORDER BY trading_days DESC, start_date
LIMIT 20;
