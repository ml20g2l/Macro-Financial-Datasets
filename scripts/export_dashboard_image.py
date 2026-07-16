"""Export the README dashboard preview from the versioned processed CSVs."""

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.build_analysis import ASSET_COLORS, REGIME_ORDER

METRICS_PATH = ROOT / "data/processed/regime_asset_metrics.csv"
CORRELATIONS_PATH = ROOT / "data/processed/regime_correlations.csv"
OUTPUT_PATH = ROOT / "outputs/dashboard_exports/macro_regime_dashboard.png"

TICKER_ORDER = ["GLD", "IEF", "SPY"]
PAIR_ORDER = [("SPY", "IEF"), ("SPY", "GLD"), ("IEF", "GLD")]
PAIR_LABELS = ["SPY–IEF", "SPY–GLD", "IEF–GLD"]
BACKGROUND = "#F6F7F9"
PANEL = "#FFFFFF"
TEXT = "#172033"
MUTED = "#667085"
GRID = "#E5E7EB"


def style_panel(axis: plt.Axes, title: str, subtitle: str) -> None:
    axis.set_facecolor(PANEL)
    axis.set_title(title, loc="left", fontsize=13, fontweight="bold", color=TEXT, pad=22)
    axis.text(
        0,
        1.02,
        subtitle,
        transform=axis.transAxes,
        fontsize=8.5,
        color=MUTED,
        va="bottom",
    )
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.tick_params(axis="both", colors=MUTED, labelsize=8, length=0)
    axis.grid(axis="x", color=GRID, linewidth=0.7)
    axis.set_axisbelow(True)


def grouped_horizontal_bars(
    axis: plt.Axes,
    metrics: pd.DataFrame,
    column: str,
    title: str,
    subtitle: str,
    x_label: str,
) -> None:
    style_panel(axis, title, subtitle)
    y = np.arange(len(REGIME_ORDER))
    offsets = {"GLD": -0.22, "IEF": 0, "SPY": 0.22}
    for ticker in TICKER_ORDER:
        values = (
            metrics.loc[metrics["ticker"] == ticker]
            .set_index("regime")
            .reindex(REGIME_ORDER)[column]
        )
        bars = axis.barh(
            y + offsets[ticker],
            values,
            height=0.18,
            color=ASSET_COLORS[ticker],
            label=ticker,
            zorder=3,
        )
        for bar, value in zip(bars, values):
            label = f"{value:.1%}"
            if column == "max_drawdown":
                x = value - 0.008
                horizontal_alignment = "right"
            elif value >= 0:
                x = value + 0.008
                horizontal_alignment = "left"
            else:
                x = value - 0.008
                horizontal_alignment = "right"
            axis.text(
                x,
                bar.get_y() + bar.get_height() / 2,
                label,
                va="center",
                ha=horizontal_alignment,
                fontsize=7.5,
                color=TEXT,
            )
    axis.axvline(0, color="#98A2B3", linewidth=0.8)
    axis.set_yticks(y, REGIME_ORDER)
    axis.invert_yaxis()
    axis.set_xlabel(x_label, fontsize=8.5, color=MUTED, labelpad=8)
    axis.margins(x=0.14)


def heatmap(
    axis: plt.Axes,
    values: pd.DataFrame,
    title: str,
    subtitle: str,
    value_format: str,
    cmap,
    norm=None,
) -> None:
    axis.set_facecolor(PANEL)
    image = axis.imshow(values.to_numpy(), aspect="auto", cmap=cmap, norm=norm)
    axis.set_title(title, loc="left", fontsize=13, fontweight="bold", color=TEXT, pad=22)
    axis.text(
        0,
        1.02,
        subtitle,
        transform=axis.transAxes,
        fontsize=8.5,
        color=MUTED,
        va="bottom",
    )
    axis.set_xticks(np.arange(len(values.columns)), values.columns)
    axis.set_yticks(np.arange(len(values.index)), values.index)
    axis.tick_params(axis="both", colors=MUTED, labelsize=8, length=0)
    for spine in axis.spines.values():
        spine.set_visible(False)
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            value = values.iloc[row, column]
            rgba = image.cmap(image.norm(value))
            luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            axis.text(
                column,
                row,
                value_format.format(value),
                ha="center",
                va="center",
                fontsize=8.5,
                fontweight="semibold",
                color="white" if luminance < 0.55 else TEXT,
            )


def add_kpi_card(
    figure: plt.Figure,
    left: float,
    value: str,
    label: str,
    detail: str,
) -> None:
    card = FancyBboxPatch(
        (left, 0.803),
        0.215,
        0.075,
        boxstyle="round,pad=0.008,rounding_size=0.008",
        transform=figure.transFigure,
        facecolor=PANEL,
        edgecolor="#E4E7EC",
        linewidth=0.8,
    )
    figure.patches.append(card)
    figure.text(left + 0.014, 0.845, value, fontsize=16, fontweight="bold", color=TEXT)
    figure.text(left + 0.065, 0.848, label, fontsize=9, fontweight="semibold", color=TEXT)
    figure.text(left + 0.014, 0.818, detail, fontsize=7.5, color=MUTED)


def main() -> None:
    metrics = pd.read_csv(METRICS_PATH)
    correlations = pd.read_csv(CORRELATIONS_PATH)

    fig = plt.figure(figsize=(16, 10), facecolor=BACKGROUND)
    grid = fig.add_gridspec(
        2,
        12,
        left=0.045,
        right=0.97,
        bottom=0.075,
        top=0.735,
        hspace=0.45,
        wspace=1.15,
    )

    fig.text(
        0.045,
        0.955,
        "Macro Regime & Asset Performance",
        fontsize=24,
        fontweight="bold",
        color=TEXT,
    )
    fig.text(
        0.045,
        0.925,
        "How distribution-adjusted SPY, IEF, and GLD returns differed across transparent, lagged market regimes",
        fontsize=10.5,
        color=MUTED,
    )
    fig.text(
        0.97,
        0.951,
        "07 Jul 2021 – 30 Dec 2025",
        ha="right",
        fontsize=9.5,
        fontweight="semibold",
        color=TEXT,
    )
    fig.text(
        0.97,
        0.926,
        "Prior-day VIX + 63-day DGS10 signal",
        ha="right",
        fontsize=8.5,
        color=MUTED,
    )

    add_kpi_card(fig, 0.045, "1,111", "classified trading days", "After warm-up and one-day signal lag")
    add_kpi_card(fig, 0.285, "4", "market regimes", "Calm, tightening, elevated risk, stress")
    add_kpi_card(fig, 0.525, "3", "distribution-adjusted ETFs", "SPY equity · IEF Treasury · GLD gold")
    add_kpi_card(fig, 0.765, "0", "SQL reconciliation gaps", "12 metrics + 12 correlations matched")

    return_axis = fig.add_subplot(grid[0, :7])
    grouped_horizontal_bars(
        return_axis,
        metrics,
        "annualized_return",
        "Annualized return",
        "Descriptive mean daily return × 252",
        "Annualized return",
    )

    sharpe = (
        metrics.pivot(index="regime", columns="ticker", values="sharpe_ratio_rf0")
        .reindex(index=REGIME_ORDER, columns=TICKER_ORDER)
    )
    sharpe_axis = fig.add_subplot(grid[0, 8:])
    sharpe_norm = TwoSlopeNorm(
        vmin=float(sharpe.min().min()),
        vcenter=0,
        vmax=float(sharpe.max().max()),
    )
    sharpe_cmap = LinearSegmentedColormap.from_list(
        "risk_return",
        ["#B42318", "#FEE4E2", "#FFFFFF", "#D1FADF", "#027A48"],
    )
    heatmap(
        sharpe_axis,
        sharpe,
        "Sharpe ratio",
        "Annualized return ÷ volatility; 0% risk-free rate",
        "{:.2f}",
        sharpe_cmap,
        sharpe_norm,
    )

    volatility_axis = fig.add_subplot(grid[1, :4])
    grouped_horizontal_bars(
        volatility_axis,
        metrics,
        "annualized_volatility",
        "Annualized volatility",
        "Sample daily standard deviation × √252",
        "Annualized volatility",
    )

    drawdown_axis = fig.add_subplot(grid[1, 4:8])
    grouped_horizontal_bars(
        drawdown_axis,
        metrics,
        "max_drawdown",
        "Maximum drawdown",
        "Calculated within contiguous regime episodes",
        "Maximum drawdown",
    )

    correlation_values = pd.DataFrame(index=REGIME_ORDER, columns=PAIR_LABELS, dtype=float)
    for regime in REGIME_ORDER:
        for pair, label in zip(PAIR_ORDER, PAIR_LABELS):
            row = correlations[
                (correlations["regime"] == regime)
                & (
                    (
                        (correlations["asset_1"] == pair[0])
                        & (correlations["asset_2"] == pair[1])
                    )
                    | (
                        (correlations["asset_1"] == pair[1])
                        & (correlations["asset_2"] == pair[0])
                    )
                )
            ]
            correlation_values.loc[regime, label] = row["correlation"].iloc[0]
    correlation_axis = fig.add_subplot(grid[1, 9:])
    heatmap(
        correlation_axis,
        correlation_values,
        "Within-regime correlation",
        "Pearson correlation of daily returns",
        "{:.2f}",
        LinearSegmentedColormap.from_list("correlation", ["#F2F4F7", "#4C78A8"]),
    )

    handles = [
        plt.Line2D([0], [0], color=ASSET_COLORS[ticker], lw=7, solid_capstyle="round")
        for ticker in TICKER_ORDER
    ]
    fig.legend(
        handles,
        TICKER_ORDER,
        title="Asset",
        loc="upper center",
        bbox_to_anchor=(0.5, 0.903),
        ncol=3,
        frameon=False,
        fontsize=9,
        title_fontsize=8,
    )
    fig.text(
        0.045,
        0.028,
        "Method note: regime rules use prior-close information. Point estimates are descriptive, not forecasts or investment recommendations.",
        fontsize=8,
        color=MUTED,
    )
    fig.text(
        0.97,
        0.028,
        "Source: versioned processed CSVs in this repository",
        ha="right",
        fontsize=8,
        color=MUTED,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
