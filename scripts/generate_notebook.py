"""Generate the reader-facing analysis notebook with current computed results."""

from pathlib import Path

import nbformat as nbf
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
NOTEBOOK = ROOT / "notebooks/01_macro_regime_analysis.ipynb"


def pct(value: float) -> str:
    return f"{value:.1%}"


metrics = pd.read_csv(PROCESSED / "regime_asset_metrics.csv")
summary = pd.read_csv(PROCESSED / "regime_classification_summary.csv")


def metric(regime: str, ticker: str, column: str) -> float:
    return float(
        metrics.loc[(metrics["regime"] == regime) & (metrics["ticker"] == ticker), column].iloc[0]
    )


nb = nbf.v4.new_notebook()
nb.metadata.kernelspec = {"display_name": "Python 3", "language": "python", "name": "python3"}
nb.metadata.language_info = {"name": "python", "version": "3.13"}

nb.cells = [
    nbf.v4.new_markdown_cell(
        f"""# Macro Regimes and Asset Performance\n\n## tl;dr\n\n- The transparent rule classifies **{int(summary['trading_days'].sum()):,} trading days** from **{summary['first_date'].min()} to {summary['last_date'].max()}** using the prior trading day's VIX and 63-day change in the US 10-year yield.\n- During **Tightening**, GLD produced a {pct(metric('Tightening', 'GLD', 'annualized_return'))} annualised price return, while SPY returned {pct(metric('Tightening', 'SPY', 'annualized_return'))} and IEF {pct(metric('Tightening', 'IEF', 'annualized_return'))}.\n- During **Elevated risk**, GLD led at {pct(metric('Elevated risk', 'GLD', 'annualized_return'))}; SPY's volatility rose to {pct(metric('Elevated risk', 'SPY', 'annualized_volatility'))}.\n- **Stress has only {int(summary.loc[summary['regime'] == 'Stress', 'trading_days'].iloc[0])} observations.** SPY's positive conditional mean and {pct(metric('Stress', 'SPY', 'annualized_volatility'))} volatility are treated as a short-sample mean-reversion result, not evidence that equities are defensive.\n\nAll figures are descriptive associations, not forecasts or investment advice."""
    ),
    nbf.v4.new_markdown_cell(
        """## Context & Methods\n\n### Regime rules\n\nRules are evaluated in priority order using information available at the **previous trading close**:\n\n| Regime | Exact rule |\n|---|---|\n| Stress | prior VIX ≥ 30 |\n| Elevated risk | 20 ≤ prior VIX < 30 |\n| Tightening | prior VIX < 20 and prior 63-trading-day DGS10 change ≥ +0.50 percentage points |\n| Calm / easing | prior VIX < 20 and prior 63-trading-day DGS10 change < +0.50 percentage points |\n| Unclassified | any required signal is missing or the 63-day warm-up is incomplete |\n\nBoundary handling is explicit: VIX = 30 is Stress, VIX = 20 is Elevated risk, and a yield change of exactly +0.50 pp is Tightening. Stress and Elevated risk take precedence over the yield rule. Thresholds are heuristic and were **not optimised against asset returns**.\n\n### Key assumptions\n\n- Returns use the stored Yahoo Finance `close_price` series. The legacy extraction did not preserve yfinance's `auto_adjust` setting, so adjustment status is not claimed.\n- Annualised return = mean daily return × 252; annualised volatility = sample daily standard deviation × √252.\n- Sharpe ratio uses a 0% risk-free rate to keep the conditional comparison reproducible.\n- Maximum drawdown is the worst peak-to-trough loss within any contiguous episode of that regime.\n- FRED values are backward as-of joined to an asset trading date with a maximum seven-calendar-day tolerance.\n- Conditional daily observations are not independent; results are descriptive and sensitive to thresholds and the 2021–2025 sample."""
    ),
    nbf.v4.new_markdown_cell(
        """## Data\n\nModel inputs are SPY, IEF, and GLD prices from Yahoo Finance plus FRED VIXCLS and DGS10. Bank of England and ONS snapshots are retained as supplementary sources but deliberately excluded from the US-asset regime classifier. See `data/README.md` and `data/source_manifest.csv` for lineage, coverage, and freshness details."""
    ),
    nbf.v4.new_code_cell(
        """from pathlib import Path\nimport sys\nimport pandas as pd\nfrom IPython.display import Image, display\n\nPROJECT_ROOT = Path.cwd().resolve()\nif not (PROJECT_ROOT / 'src').exists():\n    PROJECT_ROOT = PROJECT_ROOT.parent\nsys.path.insert(0, str(PROJECT_ROOT))\n\nfrom src.build_analysis import run_analysis\n\npd.set_option('display.max_columns', 20)\npd.set_option('display.float_format', lambda value: f'{value:,.4f}')\nPROJECT_ROOT"""
    ),
    nbf.v4.new_code_cell(
        """# Rebuild every processed table and chart from the raw snapshots.\nresults = run_analysis(PROJECT_ROOT)\nprint(f\"Analysis window: {results['qa_dict']['analysis_start']} to {results['qa_dict']['analysis_end']}\")\nprint(f\"Classified trading days: {results['qa_dict']['classified_days']:,}\")"""
    ),
    nbf.v4.new_markdown_cell("## Results\n\n### Data-quality checks"),
    nbf.v4.new_code_cell("results['qa']"),
    nbf.v4.new_markdown_cell("### Regime classification and boundaries"),
    nbf.v4.new_code_cell(
        """classification = results['summary'].copy()\nclassification['share_of_classified_days'] = classification['share_of_classified_days'].map(lambda x: f'{x:.1%}')\nclassification"""
    ),
    nbf.v4.new_code_cell(
        """display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/macro_regime_timeline.png'), width=1000))"""
    ),
    nbf.v4.new_markdown_cell("### Return and risk metrics"),
    nbf.v4.new_code_cell(
        """metric_view = results['metrics'][['regime', 'ticker', 'observations', 'annualized_return', 'annualized_volatility', 'max_drawdown', 'sharpe_ratio_rf0']].copy()\nfor column in ['annualized_return', 'annualized_volatility', 'max_drawdown']:\n    metric_view[column] = metric_view[column].map(lambda x: f'{x:.1%}')\nmetric_view['sharpe_ratio_rf0'] = metric_view['sharpe_ratio_rf0'].map(lambda x: f'{x:.2f}')\nmetric_view"""
    ),
    nbf.v4.new_code_cell(
        """for filename in ['regime_annualized_returns.png', 'regime_annualized_volatility.png', 'regime_max_drawdown.png']:\n    display(Image(filename=str(PROJECT_ROOT / 'outputs/figures' / filename), width=950))"""
    ),
    nbf.v4.new_markdown_cell("### Conditional correlations"),
    nbf.v4.new_code_cell(
        """correlation_view = results['correlations'].copy()\ncorrelation_view['correlation'] = correlation_view['correlation'].round(2)\ncorrelation_view"""
    ),
    nbf.v4.new_code_cell(
        """display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/regime_correlations.png'), width=850))"""
    ),
    nbf.v4.new_markdown_cell(
        f"""## Takeaways\n\n1. **Gold was the clearest relative winner in tightening and elevated-risk observations.** Its annualised price return was {pct(metric('Tightening', 'GLD', 'annualized_return'))} in Tightening and {pct(metric('Elevated risk', 'GLD', 'annualized_return'))} in Elevated risk.\n2. **The bond proxy was not consistently defensive in this sample.** IEF returned {pct(metric('Tightening', 'IEF', 'annualized_return'))} in Tightening and {pct(metric('Stress', 'IEF', 'annualized_return'))} in Stress. That result is specific to a period dominated by inflation and rate shocks.\n3. **Stress estimates are fragile.** Only 62 days qualify, and the positive SPY mean combines with {pct(metric('Stress', 'SPY', 'annualized_volatility'))} annualised volatility. This is better read as short-horizon rebound behaviour than a stable regime premium.\n4. **Diversification varied by state.** SPY–IEF correlation was highest in Tightening, while IEF–GLD correlation remained positive across all regimes in this snapshot.\n\nThe next analytical step would be a robustness appendix covering alternative VIX/yield thresholds, monthly sampling, total-return data, and confidence intervals. Those tests are not claimed here."""
    ),
]

NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, NOTEBOOK)
print(NOTEBOOK)
