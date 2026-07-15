"""Build the macro-regime analytical dataset, metrics, and portfolio charts.

The regime model is deliberately deterministic and descriptive. It is not a
trading signal and its thresholds were not fitted to maximise asset returns.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd


TRADING_DAYS = 252
YIELD_LOOKBACK_DAYS = 63
VIX_ELEVATED = 20.0
VIX_STRESS = 30.0
YIELD_TIGHTENING_PP = 0.50
ASOF_TOLERANCE_DAYS = 7
TICKERS = ["SPY", "IEF", "GLD"]
REGIME_ORDER = ["Calm / easing", "Tightening", "Elevated risk", "Stress"]
REGIME_COLORS = {
    "Calm / easing": "#4C78A8",
    "Tightening": "#D4A72C",
    "Elevated risk": "#F28E2B",
    "Stress": "#B55A7A",
}
ASSET_COLORS = {"SPY": "#4C78A8", "IEF": "#D4A72C", "GLD": "#E07A5F"}


def _read_source_data(project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    asset_path = project_root / "data/raw/yahoo/asset_prices.csv"
    asset_metadata_path = project_root / "data/raw/yahoo/asset_prices_metadata.json"
    vix_path = project_root / "data/raw/fred/VIXCLS.csv"
    dgs10_path = project_root / "data/raw/fred/DGS10.csv"

    assets_raw = pd.read_csv(asset_path)
    assets_raw.columns = assets_raw.columns.str.strip().str.lower()
    assets_raw = assets_raw.rename(columns={"date": "date"})
    assets_raw["date"] = pd.to_datetime(assets_raw["date"], errors="coerce")
    assets_raw["ticker"] = assets_raw["ticker"].astype(str).str.upper().str.strip()
    assets_raw["close_price"] = pd.to_numeric(assets_raw["close_price"], errors="coerce")

    vix_raw = pd.read_csv(vix_path).rename(
        columns={"observation_date": "date", "VIXCLS": "vix"}
    )
    dgs10_raw = pd.read_csv(dgs10_path).rename(
        columns={"observation_date": "date", "DGS10": "dgs10"}
    )
    for frame, value_column in ((vix_raw, "vix"), (dgs10_raw, "dgs10")):
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")

    qa = {
        "asset_rows_raw": int(len(assets_raw)),
        "asset_duplicate_keys": int(assets_raw.duplicated(["date", "ticker"]).sum()),
        "asset_null_dates": int(assets_raw["date"].isna().sum()),
        "asset_null_prices": int(assets_raw["close_price"].isna().sum()),
        "vix_rows_raw": int(len(vix_raw)),
        "vix_duplicate_dates": int(vix_raw.duplicated(["date"]).sum()),
        "vix_null_values": int(vix_raw["vix"].isna().sum()),
        "dgs10_rows_raw": int(len(dgs10_raw)),
        "dgs10_duplicate_dates": int(dgs10_raw.duplicated(["date"]).sum()),
        "dgs10_null_values": int(dgs10_raw["dgs10"].isna().sum()),
    }
    if asset_metadata_path.exists():
        asset_metadata = json.loads(asset_metadata_path.read_text(encoding="utf-8"))
        qa.update(
            {
                "asset_price_basis": asset_metadata.get("price_basis", "unknown"),
                "asset_price_retrieved_at_utc": asset_metadata.get(
                    "retrieved_at_utc", "unknown"
                ),
                "asset_price_sha256": asset_metadata.get("sha256", "unknown"),
            }
        )

    assets = (
        assets_raw.dropna(subset=["date", "ticker", "close_price"])
        .query("ticker in @TICKERS and close_price > 0")
        .drop_duplicates(["date", "ticker"], keep="last")
        .sort_values(["date", "ticker"])
    )
    macro = (
        vix_raw.drop_duplicates("date", keep="last")
        .merge(dgs10_raw.drop_duplicates("date", keep="last"), on="date", how="outer")
        .sort_values("date")
    )
    return assets, macro, qa


def _classify_regimes(macro_aligned: pd.DataFrame) -> pd.DataFrame:
    result = macro_aligned.copy()
    result["dgs10_change_63d_pp"] = result["dgs10"] - result["dgs10"].shift(
        YIELD_LOOKBACK_DAYS
    )
    # Use information available at the previous asset close. This avoids assigning
    # today's return with today's closing VIX, which would create a mechanical
    # same-day relationship and an avoidable look-ahead bias.
    result["signal_vix"] = result["vix"].shift(1)
    result["signal_dgs10"] = result["dgs10"].shift(1)
    result["signal_dgs10_change_63d_pp"] = result["dgs10_change_63d_pp"].shift(1)
    valid = result[
        ["signal_vix", "signal_dgs10", "signal_dgs10_change_63d_pp"]
    ].notna().all(axis=1)
    conditions = [
        valid & (result["signal_vix"] >= VIX_STRESS),
        valid
        & (result["signal_vix"] >= VIX_ELEVATED)
        & (result["signal_vix"] < VIX_STRESS),
        valid
        & (result["signal_vix"] < VIX_ELEVATED)
        & (result["signal_dgs10_change_63d_pp"] >= YIELD_TIGHTENING_PP),
        valid
        & (result["signal_vix"] < VIX_ELEVATED)
        & (result["signal_dgs10_change_63d_pp"] < YIELD_TIGHTENING_PP),
    ]
    choices = ["Stress", "Elevated risk", "Tightening", "Calm / easing"]
    result["regime"] = np.select(conditions, choices, default="Unclassified")
    result["regime"] = pd.Categorical(
        result["regime"], categories=REGIME_ORDER + ["Unclassified"], ordered=True
    )
    classified = result["regime"] != "Unclassified"
    result["episode_id"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result.loc[classified, "episode_id"] = (
        result.loc[classified, "regime"]
        .astype(str)
        .ne(result.loc[classified, "regime"].astype(str).shift())
        .cumsum()
        .astype("Int64")
    )
    return result


def _max_episode_drawdown(group: pd.DataFrame) -> float:
    worst = 0.0
    for _, episode in group.groupby("episode_id", dropna=True):
        returns = episode.sort_values("date")["daily_return"].dropna().to_numpy()
        if len(returns) == 0:
            continue
        wealth = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
        running_peak = np.maximum.accumulate(wealth)
        worst = min(worst, float(np.min(wealth / running_peak - 1.0)))
    return worst


def _build_tables(project_root: Path) -> dict[str, pd.DataFrame | dict]:
    assets, macro, qa = _read_source_data(project_root)
    price_wide = assets.pivot(index="date", columns="ticker", values="close_price").sort_index()
    missing_tickers = sorted(set(TICKERS) - set(price_wide.columns))
    if missing_tickers:
        raise ValueError(f"Missing required tickers: {missing_tickers}")
    price_wide = price_wide[TICKERS].dropna(how="any")

    asset_calendar = pd.DataFrame({"date": price_wide.index}).sort_values("date")
    macro_aligned = pd.merge_asof(
        asset_calendar,
        macro.dropna(subset=["date"]).sort_values("date"),
        on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=ASOF_TOLERANCE_DAYS),
    )
    macro_aligned = _classify_regimes(macro_aligned)

    returns_wide = price_wide.pct_change(fill_method=None)
    prices_long = price_wide.rename_axis(columns="ticker").stack().rename("close_price").reset_index()
    returns_long = returns_wide.rename_axis(columns="ticker").stack().rename("daily_return").reset_index()
    daily_assets = prices_long.merge(returns_long, on=["date", "ticker"], how="left")
    daily_assets = daily_assets.merge(
        macro_aligned[
            [
                "date",
                "vix",
                "dgs10",
                "dgs10_change_63d_pp",
                "signal_vix",
                "signal_dgs10",
                "signal_dgs10_change_63d_pp",
                "regime",
                "episode_id",
            ]
        ],
        on="date",
        how="left",
    )
    daily_assets["regime"] = pd.Categorical(
        daily_assets["regime"], categories=REGIME_ORDER + ["Unclassified"], ordered=True
    )

    classified_macro = macro_aligned[macro_aligned["regime"] != "Unclassified"].copy()
    classified_assets = daily_assets[
        (daily_assets["regime"] != "Unclassified") & daily_assets["daily_return"].notna()
    ].copy()

    metric_rows = []
    for (regime, ticker), group in classified_assets.groupby(
        ["regime", "ticker"], observed=True, sort=False
    ):
        daily_return = group["daily_return"].dropna()
        annualized_return = float(daily_return.mean() * TRADING_DAYS)
        annualized_volatility = float(daily_return.std(ddof=1) * np.sqrt(TRADING_DAYS))
        metric_rows.append(
            {
                "regime": str(regime),
                "ticker": ticker,
                "observations": int(len(daily_return)),
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "max_drawdown": _max_episode_drawdown(group),
                "sharpe_ratio_rf0": (
                    annualized_return / annualized_volatility
                    if annualized_volatility > 0
                    else np.nan
                ),
                "win_rate": float((daily_return > 0).mean()),
                "conditional_cumulative_return": float((1.0 + daily_return).prod() - 1.0),
            }
        )
    metrics = pd.DataFrame(metric_rows)
    metrics["regime"] = pd.Categorical(metrics["regime"], REGIME_ORDER, ordered=True)
    metrics = metrics.sort_values(["regime", "ticker"]).reset_index(drop=True)

    summary = (
        classified_macro.groupby("regime", observed=True)
        .agg(
            trading_days=("date", "size"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            median_signal_vix=("signal_vix", "median"),
            median_signal_dgs10=("signal_dgs10", "median"),
            median_signal_dgs10_change_63d_pp=("signal_dgs10_change_63d_pp", "median"),
        )
        .reset_index()
    )
    summary["share_of_classified_days"] = summary["trading_days"] / summary["trading_days"].sum()
    summary["regime"] = pd.Categorical(summary["regime"], REGIME_ORDER, ordered=True)
    summary = summary.sort_values("regime").reset_index(drop=True)

    episodes = (
        classified_macro.groupby(["regime", "episode_id"], observed=True)
        .agg(
            start_date=("date", "min"),
            end_date=("date", "max"),
            trading_days=("date", "size"),
            median_signal_vix=("signal_vix", "median"),
            median_signal_dgs10_change_63d_pp=("signal_dgs10_change_63d_pp", "median"),
        )
        .reset_index()
        .sort_values("start_date")
    )

    correlation_rows = []
    for regime in REGIME_ORDER:
        regime_returns = classified_assets[classified_assets["regime"] == regime].pivot(
            index="date", columns="ticker", values="daily_return"
        )
        for left, right in combinations(TICKERS, 2):
            pair = regime_returns[[left, right]].dropna()
            correlation_rows.append(
                {
                    "regime": regime,
                    "asset_1": left,
                    "asset_2": right,
                    "observations": int(len(pair)),
                    "correlation": float(pair[left].corr(pair[right])),
                }
            )
    correlations = pd.DataFrame(correlation_rows)

    macro_overlap_start = max(
        macro.dropna(subset=["vix"])["date"].min(),
        macro.dropna(subset=["dgs10"])["date"].min(),
        macro_aligned["date"].min(),
    )
    macro_overlap_end = min(macro.dropna(subset=["vix", "dgs10"])["date"].max(), macro_aligned["date"].max())
    overlap_mask = macro_aligned["date"].between(macro_overlap_start, macro_overlap_end)
    qa.update(
        {
            "analysis_start": classified_macro["date"].min().date().isoformat(),
            "analysis_end": classified_macro["date"].max().date().isoformat(),
            "classified_days": int(len(classified_macro)),
            "asset_calendar_days": int(len(macro_aligned)),
            "days_before_macro_overlap": int((macro_aligned["date"] < macro_overlap_start).sum()),
            "overlap_warmup_or_missing_days": int(
                ((macro_aligned["regime"] == "Unclassified") & overlap_mask).sum()
            ),
            "asset_tickers": ",".join(TICKERS),
            "daily_asset_rows": int(len(daily_assets)),
            "daily_asset_duplicate_keys": int(daily_assets.duplicated(["date", "ticker"]).sum()),
            "classified_return_nulls": int(classified_assets["daily_return"].isna().sum()),
        }
    )
    qa_table = pd.DataFrame([{"check": key, "value": value} for key, value in qa.items()])

    return {
        "daily_macro": macro_aligned,
        "daily_assets": daily_assets,
        "summary": summary,
        "episodes": episodes,
        "metrics": metrics,
        "correlations": correlations,
        "qa": qa_table,
        "qa_dict": qa,
    }


def _save_tables(project_root: Path, results: dict[str, pd.DataFrame | dict]) -> None:
    output_dir = project_root / "data/processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "daily_macro_regimes.csv": "daily_macro",
        "daily_asset_returns.csv": "daily_assets",
        "regime_classification_summary.csv": "summary",
        "regime_episodes.csv": "episodes",
        "regime_asset_metrics.csv": "metrics",
        "regime_correlations.csv": "correlations",
        "data_quality_summary.csv": "qa",
    }
    for filename, key in files.items():
        frame = results[key]
        assert isinstance(frame, pd.DataFrame)
        frame.to_csv(output_dir / filename, index=False, date_format="%Y-%m-%d")

    metrics = results["metrics"]
    assert isinstance(metrics, pd.DataFrame)
    best_by_regime = (
        metrics.sort_values(["regime", "annualized_return"], ascending=[True, False])
        .groupby("regime", observed=True)
        .first()
        .reset_index()[["regime", "ticker", "annualized_return"]]
    )
    summary_payload = {
        "analysis_refreshed": "2026-07-15",
        "method": {
            "signal_lag_trading_days": 1,
            "vix_elevated_threshold": VIX_ELEVATED,
            "vix_stress_threshold": VIX_STRESS,
            "yield_change_lookback_trading_days": YIELD_LOOKBACK_DAYS,
            "yield_tightening_threshold_percentage_points": YIELD_TIGHTENING_PP,
            "risk_free_rate_for_sharpe": 0.0,
        },
        "qa": results["qa_dict"],
        "best_annualized_return_by_regime": best_by_regime.to_dict(orient="records"),
    }
    (output_dir / "analysis_summary.json").write_text(
        json.dumps(summary_payload, indent=2, default=str), encoding="utf-8"
    )


def _plot_timeline(project_root: Path, daily_macro: pd.DataFrame) -> None:
    plot_data = daily_macro[daily_macro["regime"] != "Unclassified"].copy()
    fig = plt.figure(figsize=(12, 5.8))
    grid = fig.add_gridspec(2, 1, height_ratios=[5, 0.55])
    ax = fig.add_subplot(grid[0])
    strip = fig.add_subplot(grid[1], sharex=ax)

    ax.plot(plot_data["date"], plot_data["vix"], color="#2F3E46", linewidth=1.2)
    ax.axhline(VIX_ELEVATED, color="#D4A72C", linestyle="--", linewidth=1, label="VIX 20")
    ax.axhline(VIX_STRESS, color="#B55A7A", linestyle="--", linewidth=1, label="VIX 30")
    ax.set_title("VIX and rule-based macro regime classification")
    ax.set_ylabel("VIX index level")
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="upper right")

    regime_codes = plot_data["regime"].cat.codes.to_numpy()[None, :]
    cmap = ListedColormap([REGIME_COLORS[name] for name in REGIME_ORDER])
    date_numbers = mdates.date2num(plot_data["date"])
    strip.imshow(
        regime_codes,
        aspect="auto",
        interpolation="nearest",
        cmap=cmap,
        extent=[date_numbers.min(), date_numbers.max(), 0, 1],
        vmin=0,
        vmax=len(REGIME_ORDER) - 1,
    )
    strip.set_yticks([])
    strip.set_ylabel("Regime", rotation=0, labelpad=30, va="center")
    strip.spines[:].set_visible(False)
    strip.xaxis_date()
    strip.xaxis.set_major_locator(mdates.YearLocator())
    strip.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    handles = [plt.Line2D([0], [0], color=REGIME_COLORS[r], lw=7) for r in REGIME_ORDER]
    fig.legend(
        handles,
        REGIME_ORDER,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.075),
        ncol=4,
        frameon=False,
    )
    fig.text(
        0.01,
        0.018,
        "Daily observations; the regime applied to each return uses the prior trading day's macro signal. Sources: FRED VIXCLS and DGS10.",
        fontsize=8,
        color="#5F6B73",
    )
    fig.subplots_adjust(left=0.08, right=0.98, top=0.91, bottom=0.22, hspace=0.12)
    fig.savefig(project_root / "outputs/figures/macro_regime_timeline.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_metric_bars(
    project_root: Path, metrics: pd.DataFrame, column: str, title: str, filename: str
) -> None:
    pivot = metrics.pivot(index="regime", columns="ticker", values=column).reindex(REGIME_ORDER)
    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(pivot.index))
    width = 0.24
    for offset, ticker in enumerate(TICKERS):
        bars = ax.bar(
            x + (offset - 1) * width,
            pivot[ticker],
            width,
            label=ticker,
            color=ASSET_COLORS[ticker],
            edgecolor="#29343A",
            linewidth=0.4,
        )
        ax.bar_label(bars, labels=[f"{value:.1%}" for value in pivot[ticker]], padding=3, fontsize=8)
    ax.axhline(0, color="#29343A", linewidth=0.9)
    ax.set_xticks(x, pivot.index)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title(title)
    ax.set_ylabel("Annualised rate" if column != "max_drawdown" else "Drawdown")
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3)
    captions = {
        "annualized_return": "2021-07 to 2025-12; returns use the stored close series. Annualised return = mean daily return × 252.",
        "annualized_volatility": "2021-07 to 2025-12; annualised volatility = sample daily standard deviation × √252.",
        "max_drawdown": "2021-07 to 2025-12; worst peak-to-trough loss within any contiguous episode of each regime.",
    }
    fig.text(
        0.01,
        0.01,
        captions[column],
        fontsize=8,
        color="#5F6B73",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(project_root / f"outputs/figures/{filename}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_correlations(project_root: Path, correlations: pd.DataFrame) -> None:
    correlations = correlations.copy()
    correlations["pair"] = correlations["asset_1"] + "–" + correlations["asset_2"]
    pair_order = ["SPY–IEF", "SPY–GLD", "IEF–GLD"]
    matrix = correlations.pivot(index="regime", columns="pair", values="correlation").reindex(
        index=REGIME_ORDER, columns=pair_order
    )
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(np.arange(len(pair_order)), pair_order)
    ax.set_yticks(np.arange(len(REGIME_ORDER)), REGIME_ORDER)
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            value = matrix.iloc[row, col]
            ax.text(col, row, f"{value:.2f}", ha="center", va="center", color="#172126")
    ax.set_title("Daily asset-return correlations by macro regime")
    colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
    colorbar.set_label("Pearson correlation")
    ax.spines[:].set_visible(False)
    fig.text(
        0.01,
        0.01,
        "Pairwise Pearson correlation of same-day price returns, 2021-07 to 2025-12. Sources: Yahoo Finance and FRED.",
        fontsize=8,
        color="#5F6B73",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(project_root / "outputs/figures/regime_correlations.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _save_charts(project_root: Path, results: dict[str, pd.DataFrame | dict]) -> None:
    figure_dir = project_root / "outputs/figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    daily_macro = results["daily_macro"]
    metrics = results["metrics"]
    correlations = results["correlations"]
    assert isinstance(daily_macro, pd.DataFrame)
    assert isinstance(metrics, pd.DataFrame)
    assert isinstance(correlations, pd.DataFrame)
    _plot_timeline(project_root, daily_macro)
    _plot_metric_bars(
        project_root,
        metrics,
        "annualized_return",
        "Annualised stored-close return by macro regime and asset",
        "regime_annualized_returns.png",
    )
    _plot_metric_bars(
        project_root,
        metrics,
        "annualized_volatility",
        "Annualised volatility by macro regime and asset",
        "regime_annualized_volatility.png",
    )
    _plot_metric_bars(
        project_root,
        metrics,
        "max_drawdown",
        "Worst within-episode drawdown by macro regime and asset",
        "regime_max_drawdown.png",
    )
    _plot_correlations(project_root, correlations)


def run_analysis(project_root: Path | str) -> dict[str, pd.DataFrame | dict]:
    root = Path(project_root).resolve()
    results = _build_tables(root)
    _save_tables(root, results)
    _save_charts(root, results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    results = run_analysis(args.project_root)
    qa = results["qa_dict"]
    print(
        f"Built analysis for {qa['analysis_start']} to {qa['analysis_end']} "
        f"using {qa['classified_days']} classified trading days."
    )


if __name__ == "__main__":
    main()
