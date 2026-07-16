# Robustness and Validation Appendix

## Data provenance

The asset snapshot was rebuilt with an explicit yfinance `auto_adjust=True` setting. The download returned 15,846 unique `(date, ticker)` rows covering SPY, IEF, and GLD from 2005-01-03 to 2025-12-30. The analysis window remains 2021-07-07 to 2025-12-30 because FRED coverage and the 63-day warm-up are binding.

## Threshold sensitivity

Six scenarios combine VIX boundaries of 20/30 or 25/35 with DGS10-change thresholds of +0.25pp, +0.50pp, or +0.75pp.

| Finding | Result across six scenarios |
|---|---|
| GLD leads Tightening | 6 of 6 |
| GLD leads Elevated risk | 3 of 6 |
| IEF Tightening return is negative | 4 of 6 |
| SPY Stress return is positive | 6 of 6 |
| Stress observations | 8 to 62 days |

![Threshold sensitivity ranges](../outputs/figures/robustness_annualized_return_ranges.png)

The large Stress ranges are an analytical result rather than a chart defect: raising the Stress boundary to VIX 35 leaves only eight observations, making annualized values extremely unstable.

## Block-bootstrap intervals

The 95% intervals use 5,000 circular moving-block resamples with five-trading-day blocks and seed 20260715.

![Block-bootstrap intervals](../outputs/figures/regime_return_bootstrap_intervals.png)

Only Calm/easing GLD and Elevated-risk GLD have baseline 95% intervals above zero. Tightening GLD remains the relative leader across threshold scenarios, but its baseline return interval still includes zero. Stress intervals are extremely wide for all three assets.

Exact interval rows are versioned in `data/processed/regime_return_confidence_intervals.csv`; all scenario metrics are in `data/processed/robustness_metrics.csv`.

## Tableau package validation

`scripts/package_tableau_workbook.py` converts the two current processed CSVs into 12-row Hyper extracts, rewires the workbook to those extracts, retains byte-for-byte copies of the source CSVs for auditability, and rejects legacy PostgreSQL, live CSV, and old-regime references. The package test opens both Hyper files and verifies their row counts.

## SQL execution status

The complete SQL sequence was executed successfully on PostgreSQL 18.3 on 16 July 2026:

1. `sql/00_schema.sql` created the raw, staging, and mart schemas.
2. `sql/01_load_raw.sql` loaded 15,846 asset rows, 1,305 VIX rows, 1,305 DGS10 rows, and 258 Bank Rate rows.
3. `sql/02_transform_regimes.sql` produced 1,111 classified days, 12 metric rows, and 12 correlation rows.
4. `sql/04_validation.sql` passed all fail-fast boundary, duplicate, null, row-count, and coverage checks.
5. `sql/05_reconcile_python_outputs.sql` reported zero metric discrepancies and zero correlation discrepancies at a `1e-10` tolerance.
6. `sql/03_analysis_queries.sql` completed all portfolio-facing result queries.

The live run exposed and resolved three parity issues: FRED release-calendar null handling, floating-point treatment at the +0.50 percentage-point boundary, and episode assignment across Unclassified dates.
