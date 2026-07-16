# Methodology

## Analytical question

How did distribution-adjusted daily returns for SPY, IEF, and GLD differ when prior-day US volatility and the recent direction of the US 10-year Treasury yield indicated calm, tightening, elevated risk, or stress?

## Data inputs

| Input | Role | Grain |
|---|---|---|
| Yahoo Finance SPY, IEF, GLD | Distribution-adjusted ETF close prices | Trading day × ticker |
| FRED VIXCLS | Volatility state | US business day |
| FRED DGS10 | 63-trading-day yield change | US business day |
| Bank of England Bank Rate | Supplementary SQL example | Policy-change date |
| ONS CPI files | Preserved provenance only | Mixed |

Asset prices are downloaded by `scripts/download_adjusted_prices.py` with yfinance `auto_adjust=True`, `actions=False`, and an exclusive end date of 2025-12-31. This produces observations through 2025-12-30 and adjusts prices for splits and cash distributions. The exact version, parameters, retrieval timestamp, coverage, and SHA-256 digest are stored in `data/raw/yahoo/asset_prices_metadata.json`.

## Alignment and regime rules

FRED observations are backward as-of joined to the asset calendar with a maximum seven-calendar-day tolerance. DGS10 change is measured over 63 asset trading days. The classification signal is lagged one trading day so the regime assigned to a return uses information available before that return.

Rules are evaluated in priority order:

1. Stress: prior VIX ≥ 30
2. Elevated risk: 20 ≤ prior VIX < 30
3. Tightening: prior VIX < 20 and prior 63-day DGS10 change ≥ +0.50 percentage points
4. Calm / easing: prior VIX < 20 and prior 63-day DGS10 change < +0.50 percentage points
5. Unclassified: a required signal is missing or the 63-day warm-up is incomplete

Boundary cases are explicit: VIX = 30 is Stress, VIX = 20 is Elevated risk, and a yield change of exactly +0.50pp is Tightening.

## Metrics

- Annualized return: arithmetic mean daily adjusted return × 252
- Annualized volatility: sample daily standard deviation × √252
- Sharpe ratio: annualized return ÷ annualized volatility, with a 0% risk-free rate
- Maximum drawdown: worst peak-to-trough loss within any contiguous episode of a regime
- Correlation: pairwise Pearson correlation of same-day adjusted returns within a regime

The project does not interpret arithmetic annualization as a realizable compounded return. Conditional cumulative return is saved separately.

## Robustness and uncertainty

Threshold sensitivity evaluates six pre-declared combinations:

- VIX boundaries: 20/30 and 25/35
- DGS10 change boundaries: +0.25pp, +0.50pp, and +0.75pp

Sampling uncertainty uses 5,000 deterministic circular moving-block bootstrap samples with five-trading-day blocks. The intervals preserve short-run dependence better than independent daily resampling but remain descriptive and do not correct for regime-selection uncertainty.

## SQL parity

The SQL pipeline implements raw, staging, and mart layers, backward as-of joins, lagged signals, metrics, episode drawdowns, and correlations. `sql/04_validation.sql` contains fail-fast checks and `sql/05_reconcile_python_outputs.sql` compares SQL results with imported Python outputs.

The full SQL sequence was executed on PostgreSQL 18.3 on 16 July 2026. The SQL marts matched all 12 Python metric rows and all 12 Python correlation rows within the `1e-10` reconciliation tolerance.
