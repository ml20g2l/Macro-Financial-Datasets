# Data inventory and lineage

## Model inputs

| File | Grain | Coverage in snapshot | Role |
|---|---|---|---|
| `raw/yahoo/asset_prices.csv` | Trading day × ticker | 2005-01-03 to 2025-12-30 | SPY, IEF, and GLD distribution-adjusted close; yfinance `auto_adjust=True` |
| `raw/fred/VIXCLS.csv` | US business day | 2021-04-07 to 2026-04-07 | VIX level used in regime rules |
| `raw/fred/DGS10.csv` | US business day | 2021-04-06 to 2026-04-06 | 10-year Treasury yield used for the 63-day change |

The analytical window is the common usable period after the 63-trading-day warm-up and one-day signal lag: **2021-07-07 to 2025-12-30**.

## Supplementary sources

| Path | Description | Model use |
|---|---|---|
| `raw/boe/bank_rate_history.csv` | Bank of England Bank Rate change history, 1975-01-20 to 2025-12-18 | Loaded and typed by SQL; not used in the US-asset regime rule |
| `raw/ons/` | ONS consumer-price reference tables | Preserved for provenance; not used in the current classifier |

BoE and ONS data are intentionally excluded from the classifier. Combining UK policy/inflation series with US asset returns and US volatility without a regional mapping and a mixed-frequency design would make the rule harder to interpret. Their presence is documented instead of implying that every stored source drives the result.

## Processed outputs

| File | Grain | Description |
|---|---|---|
| `processed/daily_macro_regimes.csv` | Trading day | Observed and lagged macro variables, regime, episode ID |
| `processed/daily_asset_returns.csv` | Trading day × ticker | Price, return, macro values, regime, episode ID |
| `processed/regime_classification_summary.csv` | Regime | Day count, share, date range, median signals |
| `processed/regime_episodes.csv` | Contiguous episode | Boundary dates and episode statistics |
| `processed/regime_asset_metrics.csv` | Regime × ticker | Return, volatility, drawdown, Sharpe ratio, win rate |
| `processed/regime_correlations.csv` | Regime × asset pair | Pairwise same-day return correlation |
| `processed/data_quality_summary.csv` | Check | Row counts, duplicates, missingness, coverage |
| `processed/robustness_metrics.csv` | Scenario × regime × ticker | Metrics for six alternative threshold scenarios |
| `processed/robustness_summary.csv` | Scenario | Stability checks and Stress sample size |
| `processed/regime_return_confidence_intervals.csv` | Regime × ticker | 95% five-day block-bootstrap return intervals |

## Freshness statement

Analysis outputs were rebuilt on **2026-07-15**. The Yahoo Finance snapshot has an explicit retrieval timestamp, parameters, yfinance version, coverage, and SHA-256 digest in `raw/yahoo/asset_prices_metadata.json`. Legacy FRED, BoE, and ONS files retain audited coverage dates because their original retrieval timestamps were not preserved. Refresh the project with `python scripts/download_adjusted_prices.py`, `python -m src.build_analysis`, and `python -m src.robustness_analysis`.
