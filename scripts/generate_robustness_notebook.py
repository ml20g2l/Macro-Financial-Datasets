"""Generate the reader-facing robustness and uncertainty notebook."""

from pathlib import Path

import nbformat as nbf
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
NOTEBOOK = ROOT / "notebooks/02_robustness_uncertainty.ipynb"

summary = pd.read_csv(PROCESSED / "robustness_summary.csv")
intervals = pd.read_csv(PROCESSED / "regime_return_confidence_intervals.csv")
stress_min = int(summary["stress_observations"].min())
stress_max = int(summary["stress_observations"].max())
nonzero = intervals[
    (intervals["ci_2_5"] > 0) | (intervals["ci_97_5"] < 0)
][["regime", "ticker"]]
nonzero_labels = ", ".join(
    f"{row.regime} {row.ticker}" for row in nonzero.itertuples(index=False)
)

nb = nbf.v4.new_notebook()
nb.metadata.kernelspec = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
nb.metadata.language_info = {"name": "python", "version": "3.13"}
nb.cells = [
    nbf.v4.new_markdown_cell(
        f"""# Robustness and Uncertainty Appendix

## tl;dr

- GLD remains the highest-return asset in **Tightening across all six threshold scenarios**.
- GLD's Elevated-risk lead is **not stable** when VIX thresholds move from 20/30 to 25/35.
- The Stress sample ranges from **{stress_min} to {stress_max} days**, demonstrating that Stress estimates are highly threshold-sensitive.
- Only **{nonzero_labels}** have 95% block-bootstrap annualized-return intervals that exclude zero.

These results support a narrower conclusion than the point estimates alone: gold's Tightening result is directionally robust, while most other regime-return claims remain uncertain."""
    ),
    nbf.v4.new_markdown_cell(
        """## Context & Methods

### Threshold sensitivity

The appendix evaluates all six combinations of:

- VIX Elevated/Stress boundaries: **20/30** and **25/35**
- 63-trading-day DGS10 change: **0.25, 0.50, and 0.75 percentage points**

Every scenario keeps the one-trading-day signal lag, priority order, data window, and metric definitions fixed. The baseline is VIX 20/30 and +0.50pp.

### Sampling uncertainty

Annualized mean daily returns use 5,000 deterministic circular moving-block bootstrap samples with five-trading-day blocks. The blocks preserve short-run dependence better than an independent daily bootstrap. Intervals are descriptive sampling ranges, not forecasts, and do not solve threshold-selection uncertainty.

### Key assumptions

- Prices are distribution-adjusted with yfinance `auto_adjust=True`.
- Threshold scenarios are pre-declared and are not optimized against returns.
- Stress observations are clustered and scarce; the VIX 35 definition leaves only eight days."""
    ),
    nbf.v4.new_markdown_cell(
        """## Data

Inputs are the versioned `data/processed/daily_asset_returns.csv` rows produced by the main pipeline. Outputs are saved in `data/processed/` and `outputs/figures/`."""
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

from src.robustness_analysis import run_robustness_analysis

pd.set_option('display.max_columns', 20)
results = run_robustness_analysis(PROJECT_ROOT)
PROJECT_ROOT"""
    ),
    nbf.v4.new_markdown_cell("## Results\n\n### Threshold sensitivity"),
    nbf.v4.new_code_cell("results['robustness_summary']"),
    nbf.v4.new_code_cell(
        "display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/robustness_annualized_return_ranges.png'), width=1050))"
    ),
    nbf.v4.new_markdown_cell("### Block-bootstrap intervals"),
    nbf.v4.new_code_cell(
        """interval_view = results['intervals'].copy()
for column in ['annualized_return', 'ci_2_5', 'ci_97_5']:
    interval_view[column] = interval_view[column].map(lambda value: f'{value:.1%}')
interval_view"""
    ),
    nbf.v4.new_code_cell(
        "display(Image(filename=str(PROJECT_ROOT / 'outputs/figures/regime_return_bootstrap_intervals.png'), width=1050))"
    ),
    nbf.v4.new_markdown_cell(
        """## Takeaways

1. **Keep the Tightening/GLD result, but phrase it as a descriptive association.** It is the most stable relative result across the tested thresholds.
2. **Do not generalize the Elevated-risk or Stress point estimates.** Classification changes materially under higher VIX boundaries, and Stress can shrink to eight observations.
3. **Most return intervals include zero.** The portfolio narrative should emphasize uncertainty and relative patterns rather than treating annualized point estimates as stable premia.
4. **The next statistical upgrade would be episode-level or stationary bootstrapping over a longer history.** The stored macro window begins in 2021, so no resampling method can substitute for missing crisis cycles."""
    ),
]

NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, NOTEBOOK)
print("notebooks/02_robustness_uncertainty.ipynb")
