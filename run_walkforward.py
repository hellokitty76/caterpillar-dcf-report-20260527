#!/usr/bin/env python3
"""End-to-end research run: timeframe + parameter walk-forward, then sizing.

    python run_walkforward.py            # SPY
    python run_walkforward.py --spx      # SPX cost/multiplier profile

Writes bot/results/walkforward.json and prints a human summary.  Every number
is out-of-sample and net of costs.  This is P4 -> P5, and (with --spx) P6.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from bot.config import spy_run, spx_run
from bot.sizing import size_for_target
from bot.walkforward import (DEFAULT_GRID, TimeframeCandidate, search_timeframes)

DATA = os.path.join(os.path.dirname(__file__), "bot", "data")

# Each timeframe points at the deepest series available for it.  The 1000-bar
# API cap means only 5-min (13d) and 2-min (6d) have enough history to validate
# out-of-sample; 1-min/3-min are shown but flagged as history-starved.
CANDIDATES = [
    TimeframeCandidate(1, os.path.join(DATA, "spy_1min.csv")),
    TimeframeCandidate(2, os.path.join(DATA, "spy_2min.csv")),
    TimeframeCandidate(3, os.path.join(DATA, "spy_1min.csv")),   # resampled
    TimeframeCandidate(5, os.path.join(DATA, "spy_5min.csv")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spx", action="store_true", help="use SPX cost/multiplier profile")
    ap.add_argument("--target", type=float, default=500.0)
    ap.add_argument("--risk-budget", type=float, default=1000.0)
    args = ap.parse_args()

    base_cfg = spx_run() if args.spx else spy_run()
    out = search_timeframes(base_cfg, CANDIDATES, DEFAULT_GRID)

    report = {"symbol": base_cfg.symbol.symbol, "per_timeframe": {}}
    for tf, wf in out["per_timeframe"].items():
        report["per_timeframe"][tf] = {
            "oos": wf.oos.summary(),
            "folds": [
                {"train_days": f.train_days, "test_dates": f.test_dates,
                 "params": _params_brief(f.params), "test": f.test}
                for f in wf.folds
            ],
        }

    best = out["best"]
    print("=" * 68)
    print(f"  WALK-FORWARD  |  {base_cfg.symbol.symbol}  |  net of costs, out-of-sample")
    print("=" * 68)
    for tf in sorted(report["per_timeframe"]):
        s = report["per_timeframe"][tf]["oos"]
        tag = "  <-- best" if best and best.timeframe_min == tf else ""
        if s["trades"] == 0:
            print(f"  {tf:>2}-min : no OOS trades (insufficient history){tag}")
        else:
            print(f"  {tf:>2}-min : OOS net/day ${s['net_per_day']:>8.2f} | "
                  f"trades {s['trades']:>3} | win {s['win_rate']:.0%} | "
                  f"PF {s['profit_factor']}{tag}")

    if best is None or best.oos.n == 0:
        report["conclusion"] = "No timeframe produced a validated OOS sample."
        _save(report)
        print("\n  No validated edge on unseen data with current data/costs.")
        return

    sizing = size_for_target(best.oos, args.target, args.risk_budget)
    report["chosen_timeframe"] = best.timeframe_min
    report["sizing"] = sizing.as_dict()

    print("-" * 68)
    print(f"  Chosen timeframe: {best.timeframe_min}-min")
    print(f"  OOS edge (1 contract): ${best.oos.net_per_day:.2f}/day over "
          f"{best.oos.days} unseen days, {best.oos.n} trades")
    print("-" * 68)
    print(f"  Sizing to ${args.target:.0f}/day target:")
    print(f"    feasible          : {sizing.feasible}")
    print(f"    contracts         : {sizing.contracts}")
    print(f"    expected net/day  : ${sizing.expected_net_per_day:.2f}")
    print(f"    binding constraint: {sizing.binding_constraint}")
    print(f"    {sizing.notes}")
    _save(report)
    print(f"\n  Full report -> bot/results/walkforward.json")


def _params_brief(p) -> dict:
    return {"timeframe_min": p.timeframe_min, "breakout_lookback": p.breakout_lookback,
            "ema_fast": p.ema_fast, "ema_slow": p.ema_slow,
            "mom_thresh_atr": p.mom_thresh_atr, "trail_atr": p.trail_atr,
            "stop_atr": p.stop_atr}


def _save(report: dict) -> None:
    os.makedirs(os.path.join("bot", "results"), exist_ok=True)
    with open(os.path.join("bot", "results", "walkforward.json"), "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
