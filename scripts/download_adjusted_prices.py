"""Download reproducible distribution-adjusted ETF prices from Yahoo Finance.

The analysis uses ``auto_adjust=True`` explicitly so the stored ``close_price``
series incorporates splits and cash distributions. The end date is exclusive in
yfinance, therefore ``2025-12-31`` retains observations through 2025-12-30.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


TICKERS = ["SPY", "IEF", "GLD"]
START_DATE = "2005-01-03"
END_DATE_EXCLUSIVE = "2025-12-31"


def download_prices(output_path: Path) -> pd.DataFrame:
    downloaded = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE_EXCLUSIVE,
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
        group_by="column",
        multi_level_index=True,
    )
    if downloaded.empty:
        raise RuntimeError("Yahoo Finance returned no rows")

    close = downloaded["Close"].copy()
    missing_tickers = sorted(set(TICKERS) - set(close.columns))
    if missing_tickers:
        raise RuntimeError(f"Missing downloaded tickers: {missing_tickers}")

    prices = (
        close[TICKERS]
        .rename_axis(index="date", columns="ticker")
        .stack(future_stack=True)
        .rename("close_price")
        .reset_index()
    )
    prices["date"] = pd.to_datetime(prices["date"]).dt.tz_localize(None)
    prices["ticker"] = prices["ticker"].astype(str)
    prices["close_price"] = pd.to_numeric(prices["close_price"], errors="raise")
    prices = prices.sort_values(["date", "ticker"]).reset_index(drop=True)

    if prices.duplicated(["date", "ticker"]).any():
        raise RuntimeError("Downloaded prices contain duplicate (date, ticker) keys")
    if prices["close_price"].isna().any() or (prices["close_price"] <= 0).any():
        raise RuntimeError("Downloaded prices contain null or non-positive values")
    if set(prices["ticker"]) != set(TICKERS):
        raise RuntimeError("Downloaded prices do not cover every required ticker")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(output_path, index=False, date_format="%Y-%m-%d")

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    coverage = (
        prices.groupby("ticker")
        .agg(first_date=("date", "min"), last_date=("date", "max"), rows=("date", "size"))
        .reset_index()
    )
    metadata = {
        "source": "Yahoo Finance via yfinance",
        "yfinance_version": yf.__version__,
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "parameters": {
            "tickers": TICKERS,
            "start": START_DATE,
            "end_exclusive": END_DATE_EXCLUSIVE,
            "interval": "1d",
            "auto_adjust": True,
            "actions": False,
        },
        "price_basis": "distribution-adjusted close (splits and cash distributions)",
        "rows": int(len(prices)),
        "coverage": coverage.assign(
            first_date=coverage["first_date"].dt.date.astype(str),
            last_date=coverage["last_date"].dt.date.astype(str),
        ).to_dict(orient="records"),
        "sha256": digest,
    }
    metadata_path = output_path.with_name("asset_prices_metadata.json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return prices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/yahoo/asset_prices.csv"),
        help="Output CSV path relative to the repository root",
    )
    args = parser.parse_args()
    prices = download_prices(args.output)
    print(
        f"Wrote {len(prices):,} adjusted-price rows to {args.output} "
        f"({prices['date'].min().date()} to {prices['date'].max().date()})"
    )


if __name__ == "__main__":
    main()
