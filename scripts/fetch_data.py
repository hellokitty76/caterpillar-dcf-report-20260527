#!/usr/bin/env python3
"""Convert IBKR get_price_history JSON responses into the bot's CSV format.

The engine reads a plain CSV (time, open, high, low, close, volume).  This
script is the documented, reproducible bridge from raw IBKR pulls to that CSV,
and the single place you swap in a *different* / *cleaner* data source.

WHY A CONVERTER AND NOT A LIVE FETCHER
--------------------------------------
The market-data pulls in this environment come through the IBKR MCP tool
`get_price_history`, which a plain Python process cannot call.  So the workflow
is two-step:

  1. An operator (or the agent) calls get_price_history and saves each JSON
     response to a file, e.g.:
         step=FIVE_MINS, step_count=1000, outside_rth=false, security_type=STK
     Two hard limits to know:
       * <= 1000 data points per call;
       * every call ends at "now" -- there is NO start-date parameter, so you
         cannot reach older intraday history through this tool.  Max intraday
         lookback: ~12.8 trading days at 5-min, ~2.5 days at 1-min.

  2. Run this script to turn those JSON files into bot/data/*.csv.

TO USE A DIFFERENT DATA SOURCE (e.g. a vendor with deep, clean history):
just produce a CSV with the six columns below and drop it in bot/data/.
Nothing else in the codebase assumes IBKR.

    python scripts/fetch_data.py IN.json OUT.csv
    python scripts/fetch_data.py --dir tool-results/  # batch by step size
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys


def convert(src_json: str, dst_csv: str) -> int:
    with open(src_json) as f:
        d = json.load(f)
    cols = ("time", "open", "high", "low", "close", "volume")
    for c in cols:
        if c not in d:
            raise ValueError(f"{src_json}: missing '{c}' -- not an IBKR price payload")
    n = len(d["time"])
    os.makedirs(os.path.dirname(os.path.abspath(dst_csv)), exist_ok=True)
    with open(dst_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i in range(n):
            w.writerow([d[c][i] for c in cols])
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", help="input JSON file")
    ap.add_argument("dst", nargs="?", help="output CSV file")
    args = ap.parse_args()
    if not args.src or not args.dst:
        ap.print_help()
        sys.exit(1)
    n = convert(args.src, args.dst)
    print(f"wrote {n} bars -> {args.dst}")


if __name__ == "__main__":
    main()
