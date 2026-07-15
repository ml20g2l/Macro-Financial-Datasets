"""Generate the reader-facing baseline analysis notebook."""

from pathlib import Path

import nbformat as nbf
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
NOTEBOOK = ROOT / "notebooks/01_macro_regime_analysis.ipynb"

metrics = pd.read_csv(PROCESSED / "regime_asset_metrics.csv")
summary = pd.read_csv(PROCESSED / "regime_classification_summary.csv")


def metric(regime: str, ticker: str, column: str) -> float:
    return float(
        metrics.loc[
            (metrics["regime"] == regime) & (metrics["ticker"] == ticker), column
        ].iloc[0]
    )


def pct(value: float) -> str:
    return f"{value:.1%}"


nb = nbf.v4.new_notebook()
nb.metadata.kernelspec = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
nb.metadata.language_info = {"name": "python", "version": "3.13"}
nb.cells = [
    nbf.v4.new_markdown_cell(
        f"""# Macro Regimes and Asset Performance

## tl;dr

- The transparent rule classifies **{int(summary['trading_days'].sum()):,} trading days** from **{summary['first_date'].min()} to {summary['last_date'].max()}** using prior-day VIX and the 63-day change in the US 10-year yield.
- In the baseline **Tightening** regime, GLD returned {pct(metric('Tightening', 'GLD', 'annualized_return'))} annualized versus {pct(metric('Tightening', 'SPY', 'annualized_return'))} for SPY and {pct(metric('Tightening', 'IEF', 'annualized_return'))} for IEF.
- In **Elevated risk**, GLD led at {pct(metric('Elevated risk', 'GLD', 'annualized_return'))}, but the companion sensitivity analysis shows that this lead is not stable under every threshold definition.
- **Stress has only {int(summary.loc[summary['regime'] == 'Stress', 'trading_days'].iloc[0])} baseline observations.** Its point estimates are treated as unstable rather than evidence of a defensive premium.

All results are descriptive associations, not forecasts or investment advice."""
    ),
    nbf.v4.new_markdown_cell(
        """## Context & Methods

### Regime rules

Rules use information available at the **previous trading close** and are evaluated in priority order:

| Regime | Exact rule |
|---|---|
| Stress | prior VIX ≥ 30 |
| Elevated risk | 20 ≤ prior VIX < 30 |
| Tightening | prior VIX < 20 and prior 63-trading-day DGS10 change ≥ +0.50 percentage points |
| Calm / easing | prior VIX < 20 and prior 63-trading-day DGS10 change < +0.50 percentage points |
| Unclassified | a required signal is missing or the 63-day warm-up is incomplete |

Boundary handling is explicit. Thresholds are heuristic and were not optimized against returns.

### Key assumptions

- Prices are downloaded with yfinance `auto_adjust=True`, incorporating splits and cash distributions. Parameters and SHA-256 are stored in `data/raw/yahoo/asset_prices_metadata.json`.
- Annualized return = mean daily return × 252; annualized volatility = sample daily standard deviation × √252.
- Sharpe uses a 0% risk-free rate.
- Maximum drawdown is the worst peak-to-trough loss within a contiguous regime episode.
- FRED values are backward as-of joined with a seven-calendar-day tolerance.
- Daily observations are dependent and results are sensitive to thresholds and the 2021–2025 window."""
    ),
    nbf.v4.new_markdown_cell(
        """## Data

Model inputs are distribution-adjusted SPY, IEF, and GLD prices plus FRED VIXCLS and DGS10. BoE and ONS snapshots are supplementary and excluded from the US classifier. See `data/README.md` and `data/source_manifest.csv` for lineage."""
    ),
    nbf.v4.new_code_cell(
        """from pathlib import Path
import sys
import pandas as pd
from IPython.display import Image, display

PROJECT_ROOT = Path.cwd().resolve()
if not (PROJECT_ROOT / 'src').exists():
    PROJECT_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.build_analysis import run_analysis

pd.set_option('display.max_columns', 20)
results = run_analysis(PROJECT_ROOT)
print(f"Analysis window: {results['qa_dict']['analysis_start']} to {results['qa_dict']['analysis_end']}")
print(f"Classified trading days: {results['qa_dict']['classified_days']:,}")"""
    ),
    nbf.v4.new_markdown_cell("## Results\n\n### Data-quality checks"),
    nbf.v4.new_code_cell("results['qa']"),
    nbf.v4.new_markdown_cell("### Regime classification"),
    nbf.v4.new_code_cell(
        """classification = results['summary'].copy()
classification['share_of_classified_days'] = classification['share_of_classified_days'].map(lambda value: f'{value:.1%}')
classification"""
    ),
    nbf.v4.new_code_cell(
        "display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/macro_regime_timeline.png'), width=1000))"
    ),
    nbf.v4.new_markdown_cell("### Return and risk metrics"),
    nbf.v4.new_code_cell(
        """metric_view = results['metrics'][['regime', 'ticker', 'observations', 'annualized_return', 'annualized_volatility', 'max_drawdown', 'sharpe_ratio_rf0']].copy()
for column in ['annualized_return', 'annualized_volatility', 'max_drawdown']:
    metric_view[column] = metric_view[column].map(lambda value: f'{value:.1%}')
metric_view['sharpe_ratio_rf0'] = metric_view['sharpe_ratio_rf0'].map(lambda value: f'{value:.2f}')
metric_view"""
    ),
    nbf.v4.new_code_cell(
        """for filename in ['regime_annualized_returns.png', 'regime_annualized_volatility.png', 'regime_max_drawdown.png']:
    display(Image(filename=str(PROJECT_ROOT / 'outputs/figures' / filename), width=950))"""
    ),
    nbf.v4.new_markdown_cell("### Conditional correlations"),
    nbf.v4.new_code_cell(
        """correlation_view = results['correlations'].copy()
correlation_view['correlation'] = correlation_view['correlation'].round(2)
correlation_view"""
    ),
    nbf.v4.new_code_cell(
        "display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/regime_correlations.png'), width=850))"
    ),
    nbf.v4.new_markdown_cell(
        f"""## Takeaways

1. **GLD is the strongest relative baseline performer in Tightening and Elevated risk.** Its annualized returns are {pct(metric('Tightening', 'GLD', 'annualized_return'))} and {pct(metric('Elevated risk', 'GLD', 'annualized_return'))}, respectively.
2. **IEF is not consistently defensive in this sample.** Its Tightening return is {pct(metric('Tightening', 'IEF', 'annualized_return'))}.
3. **Stress estimates are fragile.** Only 62 days qualify and the companion bootstrap intervals are extremely wide.
4. **Sensitivity changes the narrative.** `02_robustness_uncertainty.ipynb` shows GLD's Tightening lead holds across all six scenarios, while Elevated-risk leadership does not.

The evidence supports cautious relative comparisons, not stable regime premia."""
    ),
]

NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, NOTEBOOK)
print("notebooks/01_macro_regime_analysis.ipynb")
