"""Lightweight reproducibility checks; run directly without pytest."""

from pathlib import Path

import nbformat
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"

macro = pd.read_csv(PROCESSED / "daily_macro_regimes.csv", parse_dates=["date"])
assets = pd.read_csv(PROCESSED / "daily_asset_returns.csv", parse_dates=["date"])
metrics = pd.read_csv(PROCESSED / "regime_asset_metrics.csv")
correlations = pd.read_csv(PROCESSED / "regime_correlations.csv")

assert not macro["date"].duplicated().any()
assert not assets.duplicated(["date", "ticker"]).any()
assert set(metrics["regime"]) == {"Calm / easing", "Tightening", "Elevated risk", "Stress"}
assert set(metrics["ticker"]) == {"SPY", "IEF", "GLD"}
assert len(metrics) == 12
assert len(correlations) == 12

classified = macro[macro["regime"] != "Unclassified"]
assert len(classified) == 1111
assert classified["date"].min().strftime("%Y-%m-%d") == "2021-07-07"
assert classified["date"].max().strftime("%Y-%m-%d") == "2025-12-30"

assert (classified.loc[classified["regime"] == "Stress", "signal_vix"] >= 30).all()
assert classified.loc[classified["regime"] == "Elevated risk", "signal_vix"].between(
    20, 30, inclusive="left"
).all()
tightening = classified[classified["regime"] == "Tightening"]
assert (tightening["signal_vix"] < 20).all()
assert (tightening["signal_dgs10_change_63d_pp"] >= 0.50).all()
calm = classified[classified["regime"] == "Calm / easing"]
assert (calm["signal_vix"] < 20).all()
assert (calm["signal_dgs10_change_63d_pp"] < 0.50).all()

# Independent spot check of the highest-profile Tightening/GLD annualised return.
sample = assets[(assets["regime"] == "Tightening") & (assets["ticker"] == "GLD")]
recomputed = sample["daily_return"].mean() * 252
reported = metrics.loc[
    (metrics["regime"] == "Tightening") & (metrics["ticker"] == "GLD"),
    "annualized_return",
].iloc[0]
assert np.isclose(recomputed, reported, rtol=0, atol=1e-12)

for figure in (
    "macro_regime_timeline.png",
    "regime_annualized_returns.png",
    "regime_annualized_volatility.png",
    "regime_max_drawdown.png",
    "regime_correlations.png",
):
    path = ROOT / "outputs/figures" / figure
    assert path.exists() and path.stat().st_size > 10_000

notebook = nbformat.read(ROOT / "notebooks/01_macro_regime_analysis.ipynb", as_version=4)
assert notebook.cells[0].cell_type == "markdown" and "## tl;dr" in notebook.cells[0].source
errors = [
    output
    for cell in notebook.cells
    if cell.cell_type == "code"
    for output in cell.get("outputs", [])
    if output.get("output_type") == "error"
]
assert not errors

print("All analysis, boundary, output, and notebook checks passed.")
