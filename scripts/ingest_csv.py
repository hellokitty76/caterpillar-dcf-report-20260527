#!/usr/bin/env python3
"""Ingest a local 2024/2025 (or any non-2026) intraday CSV into bot/data/.

Drops the friction out of using your own history: point it at whatever file
you have, it auto-detects the columns/timestamp layout (via bot.data.read_bars_csv),
writes the canonical `time,open,high,low,close,volume` CSV, and prints a
coverage report.  It EXCLUDES the 2026 regime by default (per the rule that
2026 is anomalous and unfit for training) and tells you how many rows it dropped.

    python scripts/ingest_csv.py my_spy_2024_2025_1min.csv bot/data/spy_train_1min.csv
    python scripts/ingest_csv.py IN.csv OUT.csv --assume-tz UTC        # if file is UTC-naive
    python scripts/ingest_csv.py IN.csv OUT.csv --keep-2026            # override the exclusion
    python scripts/ingest_csv.py IN.csv --preview                      # inspect only, no write

Then point run_walkforward.py's CANDIDATES (or load_days) at the new CSV.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from bot.data import read_bars_csv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--assume-tz", default="America/New_York",
                    help="tz for naive timestamps (default US/Eastern)")
    ap.add_argument("--keep-2026", action="store_true",
                    help="do NOT drop 2026 rows (off by default)")
    ap.add_argument("--preview", action="store_true", help="report only, no write")
    args = ap.parse_args()

    df = read_bars_csv(args.src, assume_tz=args.assume_tz)
    if df.empty:
        print("no usable rows parsed -- check the file's columns/timestamps")
        sys.exit(1)

    years = df.index.year
    n_2026 = int((years == 2026).sum())
    if not args.keep_2026 and n_2026:
        df = df[years != 2026]
        print(f"excluded {n_2026} rows dated 2026 (anomalous regime).")

    days = sorted({d.date().isoformat() for d in df.index})
    print(f"parsed {len(df)} bars over {len(days)} trading days")
    if days:
        print(f"  span: {days[0]} -> {days[-1]}")
        by_year = pd.Series(df.index.year).value_counts().sort_index()
        print("  bars by year:", dict(by_year))
    print("  sample:")
    print(df.head(3).to_string())

    if args.preview or not args.dst:
        if not args.dst:
            print("\n(no output path given -> preview only)")
        return

    out = df.reset_index().rename(columns={"ts": "time"})
    out["time"] = out["time"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    out.to_csv(args.dst, index=False)
    print(f"\nwrote {len(out)} bars -> {args.dst}")


if __name__ == "__main__":
    main()
