"""Lightweight reproducibility checks; run directly without pytest."""

from pathlib import Path
import hashlib
import json
import sys
import tempfile
import zipfile

import nbformat
import numpy as np
import pandas as pd
from tableauhyperapi import Connection, HyperProcess, Telemetry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.build_analysis import ASSET_COLORS

PROCESSED = ROOT / "data/processed"

macro = pd.read_csv(PROCESSED / "daily_macro_regimes.csv", parse_dates=["date"])
assets = pd.read_csv(PROCESSED / "daily_asset_returns.csv", parse_dates=["date"])
metrics = pd.read_csv(PROCESSED / "regime_asset_metrics.csv")
correlations = pd.read_csv(PROCESSED / "regime_correlations.csv")
robustness = pd.read_csv(PROCESSED / "robustness_metrics.csv")
robustness_summary = pd.read_csv(PROCESSED / "robustness_summary.csv")
intervals = pd.read_csv(PROCESSED / "regime_return_confidence_intervals.csv")

assert not macro["date"].duplicated().any()
assert not assets.duplicated(["date", "ticker"]).any()
assert set(metrics["regime"]) == {"Calm / easing", "Tightening", "Elevated risk", "Stress"}
assert set(metrics["ticker"]) == {"SPY", "IEF", "GLD"}
assert ASSET_COLORS == {
    "SPY": "#4C78A8",
    "IEF": "#F28E2B",
    "GLD": "#D4A72C",
}
assert len(metrics) == 12
assert len(correlations) == 12
assert len(robustness) == 72
assert len(robustness_summary) == 6
assert len(intervals) == 12

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

baseline = robustness[robustness["is_baseline"]].sort_values(["regime", "ticker"])
reported_sorted = metrics.sort_values(["regime", "ticker"])
assert len(baseline) == 12
assert np.allclose(
    baseline["annualized_return"],
    reported_sorted["annualized_return"],
    rtol=0,
    atol=1e-12,
)
assert robustness_summary["gld_leads_tightening"].all()
assert not robustness_summary["gld_leads_elevated_risk"].all()
assert robustness_summary["stress_observations"].min() == 8
assert robustness_summary["stress_observations"].max() == 62
assert (intervals["ci_2_5"] <= intervals["annualized_return"]).all()
assert (intervals["annualized_return"] <= intervals["ci_97_5"]).all()

asset_path = ROOT / "data/raw/yahoo/asset_prices.csv"
asset_metadata = json.loads(
    (ROOT / "data/raw/yahoo/asset_prices_metadata.json").read_text(encoding="utf-8")
)
assert asset_metadata["parameters"]["auto_adjust"] is True
assert asset_metadata["rows"] == 15846
assert asset_metadata["sha256"] == hashlib.sha256(asset_path.read_bytes()).hexdigest()

for figure in (
    "macro_regime_timeline.png",
    "regime_annualized_returns.png",
    "regime_annualized_volatility.png",
    "regime_max_drawdown.png",
    "regime_correlations.png",
    "robustness_annualized_return_ranges.png",
    "regime_return_bootstrap_intervals.png",
):
    path = ROOT / "outputs/figures" / figure
    assert path.exists() and path.stat().st_size > 10_000

dashboard_preview = ROOT / "outputs/dashboard_exports/macro_regime_dashboard.png"
assert dashboard_preview.exists() and dashboard_preview.stat().st_size > 100_000

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

robustness_notebook = nbformat.read(
    ROOT / "notebooks/02_robustness_uncertainty.ipynb", as_version=4
)
assert "## tl;dr" in robustness_notebook.cells[0].source
robustness_errors = [
    output
    for cell in robustness_notebook.cells
    if cell.cell_type == "code"
    for output in cell.get("outputs", [])
    if output.get("output_type") == "error"
]
assert not robustness_errors

workbook = ROOT / "tableau/asset_performance_across_macro_regimes.twbx"
with zipfile.ZipFile(workbook) as package:
    names = set(package.namelist())
    assert names == {
        "asset_performance_across_macro_regimes.twb",
        "Data/processed/regime_asset_metrics.csv",
        "Data/processed/regime_correlations.csv",
        "Data/Extracts/regime_asset_metrics.hyper",
        "Data/Extracts/regime_correlations.hyper",
    }
    assert package.read("Data/processed/regime_asset_metrics.csv") == (
        PROCESSED / "regime_asset_metrics.csv"
    ).read_bytes()
    assert package.read("Data/processed/regime_correlations.csv") == (
        PROCESSED / "regime_correlations.csv"
    ).read_bytes()
    workbook_xml = package.read("asset_performance_across_macro_regimes.twb").decode("utf-8")
    forbidden = ("postgres", 'class="textscan"', "Stress + High Yield", "Mixed")
    assert not any(term.lower() in workbook_xml.lower() for term in forbidden)
    assert workbook_xml.count('class="hyper"') == 2
    assert workbook_xml.count('table="[Extract].[Extract]"') == 4
    for ticker, color in ASSET_COLORS.items():
        assert (
            workbook_xml.count(
                f'<map to="{color}"><bucket>"{ticker}"</bucket></map>'
            )
            == 1
        )
    assert workbook_xml.count("<color column=") == 3

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        expected_rows = {
            "regime_asset_metrics": len(metrics),
            "regime_correlations": len(correlations),
        }
        for extract_name, row_count in expected_rows.items():
            extract_path = temporary_root / f"{extract_name}.hyper"
            extract_path.write_bytes(
                package.read(f"Data/Extracts/{extract_name}.hyper")
            )
            with HyperProcess(
                Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU
            ) as process:
                with Connection(process.endpoint, extract_path) as connection:
                    actual_rows = connection.execute_scalar_query(
                        'SELECT count(*) FROM "Extract"."Extract"'
                    )
            assert actual_rows == row_count

print("All analysis, boundary, output, and notebook checks passed.")
