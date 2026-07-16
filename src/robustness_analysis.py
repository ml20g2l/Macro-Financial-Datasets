"""Threshold sensitivity and block-bootstrap uncertainty analysis."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

from src.build_analysis import (
    ASSET_COLORS,
    ASSET_LIGHT_COLORS,
    REGIME_ORDER,
    TICKERS,
    TRADING_DAYS,
)


SCENARIOS = [
    {
        "scenario": f"VIX {elevated:.0f}/{stress:.0f}; yield {yield_threshold:.2f}pp",
        "vix_elevated": elevated,
        "vix_stress": stress,
        "yield_tightening_pp": yield_threshold,
        "is_baseline": elevated == 20 and stress == 30 and yield_threshold == 0.50,
    }
    for elevated, stress in ((20.0, 30.0), (25.0, 35.0))
    for yield_threshold in (0.25, 0.50, 0.75)
]
BOOTSTRAP_SAMPLES = 5_000
BOOTSTRAP_BLOCK_SIZE = 5
BOOTSTRAP_SEED = 20260715


def _classify(frame: pd.DataFrame, scenario: dict) -> pd.Series:
    valid = frame[
        ["signal_vix", "signal_dgs10", "signal_dgs10_change_63d_pp"]
    ].notna().all(axis=1)
    conditions = [
        valid & (frame["signal_vix"] >= scenario["vix_stress"]),
        valid
        & (frame["signal_vix"] >= scenario["vix_elevated"])
        & (frame["signal_vix"] < scenario["vix_stress"]),
        valid
        & (frame["signal_vix"] < scenario["vix_elevated"])
        & (
            frame["signal_dgs10_change_63d_pp"]
            >= scenario["yield_tightening_pp"]
        ),
        valid
        & (frame["signal_vix"] < scenario["vix_elevated"])
        & (
            frame["signal_dgs10_change_63d_pp"]
            < scenario["yield_tightening_pp"]
        ),
    ]
    return pd.Series(
        np.select(
            conditions,
            ["Stress", "Elevated risk", "Tightening", "Calm / easing"],
            default="Unclassified",
        ),
        index=frame.index,
        name="regime_sensitivity",
    )


def _scenario_metrics(daily_assets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    metric_rows: list[dict] = []
    summary_rows: list[dict] = []
    for scenario in SCENARIOS:
        classified = daily_assets.copy()
        classified["regime_sensitivity"] = _classify(classified, scenario)
        classified = classified[
            (classified["regime_sensitivity"] != "Unclassified")
            & classified["daily_return"].notna()
        ]
        for (regime, ticker), group in classified.groupby(
            ["regime_sensitivity", "ticker"], sort=False
        ):
            returns = group["daily_return"]
            annualized_return = float(returns.mean() * TRADING_DAYS)
            annualized_volatility = float(
                returns.std(ddof=1) * np.sqrt(TRADING_DAYS)
            )
            metric_rows.append(
                {
                    **scenario,
                    "regime": regime,
                    "ticker": ticker,
                    "observations": int(len(returns)),
                    "annualized_return": annualized_return,
                    "annualized_volatility": annualized_volatility,
                    "sharpe_ratio_rf0": (
                        annualized_return / annualized_volatility
                        if annualized_volatility > 0
                        else np.nan
                    ),
                }
            )

        scenario_metrics = pd.DataFrame(
            [row for row in metric_rows if row["scenario"] == scenario["scenario"]]
        )
        leaders = (
            scenario_metrics.sort_values(
                ["regime", "annualized_return"], ascending=[True, False]
            )
            .groupby("regime")
            .first()["ticker"]
            .to_dict()
        )
        def value(regime: str, ticker: str, column: str) -> float:
            return float(
                scenario_metrics.loc[
                    (scenario_metrics["regime"] == regime)
                    & (scenario_metrics["ticker"] == ticker),
                    column,
                ].iloc[0]
            )

        summary_rows.append(
            {
                **scenario,
                "classified_days": int(
                    classified.loc[classified["ticker"] == "SPY", "date"].nunique()
                ),
                "gld_leads_tightening": leaders.get("Tightening") == "GLD",
                "gld_leads_elevated_risk": leaders.get("Elevated risk") == "GLD",
                "ief_tightening_return_negative": value(
                    "Tightening", "IEF", "annualized_return"
                )
                < 0,
                "stress_spy_return_positive": value(
                    "Stress", "SPY", "annualized_return"
                )
                > 0,
                "stress_observations": int(
                    value("Stress", "SPY", "observations")
                ),
            }
        )

    metrics = pd.DataFrame(metric_rows)
    metrics["regime"] = pd.Categorical(metrics["regime"], REGIME_ORDER, ordered=True)
    metrics = metrics.sort_values(["scenario", "regime", "ticker"]).reset_index(drop=True)
    return metrics, pd.DataFrame(summary_rows)


def _moving_block_bootstrap_mean(
    values: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n = len(values)
    block_size = min(BOOTSTRAP_BLOCK_SIZE, n)
    blocks_needed = int(np.ceil(n / block_size))
    starts = rng.integers(0, n, size=(BOOTSTRAP_SAMPLES, blocks_needed))
    offsets = np.arange(block_size)
    indices = (starts[:, :, None] + offsets[None, None, :]) % n
    samples = values[indices].reshape(BOOTSTRAP_SAMPLES, -1)[:, :n]
    return samples.mean(axis=1) * TRADING_DAYS


def _confidence_intervals(daily_assets: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    rows: list[dict] = []
    classified = daily_assets[
        (daily_assets["regime"] != "Unclassified")
        & daily_assets["daily_return"].notna()
    ].copy()
    for regime in REGIME_ORDER:
        for ticker in TICKERS:
            values = (
                classified.loc[
                    (classified["regime"] == regime)
                    & (classified["ticker"] == ticker),
                    "daily_return",
                ]
                .sort_index()
                .to_numpy()
            )
            bootstrap = _moving_block_bootstrap_mean(values, rng)
            rows.append(
                {
                    "regime": regime,
                    "ticker": ticker,
                    "observations": int(len(values)),
                    "annualized_return": float(values.mean() * TRADING_DAYS),
                    "ci_2_5": float(np.quantile(bootstrap, 0.025)),
                    "ci_97_5": float(np.quantile(bootstrap, 0.975)),
                    "bootstrap_samples": BOOTSTRAP_SAMPLES,
                    "block_size_trading_days": min(BOOTSTRAP_BLOCK_SIZE, len(values)),
                    "seed": BOOTSTRAP_SEED,
                }
            )
    return pd.DataFrame(rows)


def _plot_robustness_ranges(
    project_root: Path, robustness_metrics: pd.DataFrame
) -> None:
    baseline = robustness_metrics[robustness_metrics["is_baseline"]].copy()
    ranges = (
        robustness_metrics.groupby(["regime", "ticker"], observed=True)[
            "annualized_return"
        ]
        .agg(min_return="min", max_return="max")
        .reset_index()
        .merge(
            baseline[["regime", "ticker", "annualized_return"]].rename(
                columns={"annualized_return": "baseline_return"}
            ),
            on=["regime", "ticker"],
            how="left",
        )
    )
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.8), sharey=True)
    y = np.arange(len(REGIME_ORDER))
    for ax, ticker in zip(axes, TICKERS):
        view = ranges[ranges["ticker"] == ticker].set_index("regime").reindex(REGIME_ORDER)
        ax.hlines(
            y,
            view["min_return"],
            view["max_return"],
            color=ASSET_LIGHT_COLORS[ticker],
            linewidth=5,
            label="Range across 6 scenarios",
        )
        ax.scatter(
            view["baseline_return"],
            y,
            color=ASSET_COLORS[ticker],
            edgecolor="white",
            linewidth=0.7,
            s=55,
            zorder=3,
            label="Baseline",
        )
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_title(ticker)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0))
        ax.grid(axis="x", color="#E1E5E8", linewidth=0.7)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.set_yticks(y, REGIME_ORDER)
    axes[0].set_ylabel("Macro regime")
    axes[1].set_xlabel("Annualized mean daily return")
    axes[2].legend(loc="lower right", frameon=False, fontsize=8)
    fig.suptitle("Annualized returns across alternative regime thresholds", y=0.98)
    fig.text(
        0.01,
        0.015,
        "Six combinations: VIX 20/30 or 25/35 and 63-day DGS10 changes of 0.25, 0.50, or 0.75 percentage points. Baseline = 20/30 and 0.50pp. Panel x-scales differ.",
        fontsize=8,
        color="#5F6B73",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.91))
    fig.savefig(
        project_root / "outputs/figures/robustness_annualized_return_ranges.png",
        dpi=180,
        bbox_inches="tight",
    )
    plt.close(fig)


def _plot_confidence_intervals(project_root: Path, intervals: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.8), sharey=True)
    y = np.arange(len(REGIME_ORDER))
    for ax, ticker in zip(axes, TICKERS):
        view = intervals[intervals["ticker"] == ticker].set_index("regime").reindex(REGIME_ORDER)
        estimate = view["annualized_return"].to_numpy()
        lower = view["ci_2_5"].to_numpy()
        upper = view["ci_97_5"].to_numpy()
        ax.errorbar(
            estimate,
            y,
            xerr=np.vstack([estimate - lower, upper - estimate]),
            fmt="o",
            color=ASSET_COLORS[ticker],
            ecolor=ASSET_LIGHT_COLORS[ticker],
            elinewidth=3,
            capsize=4,
            markersize=6,
        )
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_title(ticker)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0))
        ax.grid(axis="x", color="#E1E5E8", linewidth=0.7)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.set_yticks(y, REGIME_ORDER)
    axes[0].set_ylabel("Macro regime")
    axes[1].set_xlabel("Annualized mean daily return")
    fig.suptitle("Annualized return estimates with 95% block-bootstrap intervals", y=0.97)
    fig.text(
        0.01,
        0.015,
        "5,000 deterministic moving-block resamples with five-trading-day circular blocks. Intervals describe sampling uncertainty, not forecast ranges. Panel x-scales differ.",
        fontsize=8,
        color="#5F6B73",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.91))
    fig.savefig(
        project_root / "outputs/figures/regime_return_bootstrap_intervals.png",
        dpi=180,
        bbox_inches="tight",
    )
    plt.close(fig)


def run_robustness_analysis(project_root: Path) -> dict[str, pd.DataFrame]:
    processed = project_root / "data/processed"
    daily_assets = pd.read_csv(
        processed / "daily_asset_returns.csv", parse_dates=["date"]
    )
    robustness_metrics, robustness_summary = _scenario_metrics(daily_assets)
    intervals = _confidence_intervals(daily_assets)

    robustness_metrics.to_csv(processed / "robustness_metrics.csv", index=False)
    robustness_summary.to_csv(processed / "robustness_summary.csv", index=False)
    intervals.to_csv(processed / "regime_return_confidence_intervals.csv", index=False)

    _plot_robustness_ranges(project_root, robustness_metrics)
    _plot_confidence_intervals(project_root, intervals)

    payload = {
        "scenarios": len(SCENARIOS),
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "block_size_trading_days": BOOTSTRAP_BLOCK_SIZE,
        "all_scenarios_gld_leads_tightening": bool(
            robustness_summary["gld_leads_tightening"].all()
        ),
        "all_scenarios_gld_leads_elevated_risk": bool(
            robustness_summary["gld_leads_elevated_risk"].all()
        ),
        "all_scenarios_ief_tightening_return_negative": bool(
            robustness_summary["ief_tightening_return_negative"].all()
        ),
        "stress_observation_range": [
            int(robustness_summary["stress_observations"].min()),
            int(robustness_summary["stress_observations"].max()),
        ],
    }
    (processed / "robustness_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return {
        "robustness_metrics": robustness_metrics,
        "robustness_summary": robustness_summary,
        "intervals": intervals,
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    results = run_robustness_analysis(project_root)
    print(
        f"Built {len(results['robustness_metrics'])} threshold-sensitivity rows and "
        f"{len(results['intervals'])} confidence-interval rows."
    )


if __name__ == "__main__":
    main()
