-- Fail-fast validation checks for the PostgreSQL pipeline.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM stg.asset_prices GROUP BY date, ticker HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate (date, ticker) keys in stg.asset_prices';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mart.daily_asset_regime_returns
        WHERE regime <> 'Unclassified' AND daily_return IS NULL
    ) THEN
        RAISE EXCEPTION 'Null daily returns inside the classified analysis window';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mart.daily_macro_regimes
        WHERE regime = 'Stress' AND signal_vix < 30
    ) THEN
        RAISE EXCEPTION 'Stress threshold classification mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mart.daily_macro_regimes
        WHERE regime = 'Tightening'
          AND (signal_vix >= 20 OR signal_dgs10_change_63d_pp < 0.50)
    ) THEN
        RAISE EXCEPTION 'Tightening threshold classification mismatch';
    END IF;
END $$;

-- Reviewable row-count, coverage, and missingness report.
SELECT 'stg_asset_rows' AS check_name, count(*)::text AS check_value FROM stg.asset_prices
UNION ALL
SELECT 'classified_days', count(*)::text FROM mart.daily_macro_regimes WHERE regime <> 'Unclassified'
UNION ALL
SELECT 'analysis_start', min(date)::text FROM mart.daily_macro_regimes WHERE regime <> 'Unclassified'
UNION ALL
SELECT 'analysis_end', max(date)::text FROM mart.daily_macro_regimes WHERE regime <> 'Unclassified'
UNION ALL
SELECT 'metric_rows', count(*)::text FROM mart.regime_asset_metrics
UNION ALL
SELECT 'correlation_rows', count(*)::text FROM mart.regime_correlations;
