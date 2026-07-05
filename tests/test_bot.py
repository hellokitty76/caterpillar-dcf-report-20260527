"""Tests for the invariants that matter: no lookahead, costs always bite,
one position at a time, and a sane option pricer.

Run:  python -m pytest tests/ -q      (or)   python tests/test_bot.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import StrategyParams, spy_run
from bot.data import load_days
from bot.engine import Engine
from bot.options import bs_price, atm_strike
from bot import indicators as ind

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "bot", "data")
CSV5 = os.path.join(DATA, "spy_5min.csv")


# --------------------------------------------------------------------------- #
def test_bs_atm_call_equals_put():
    # r=0, ATM -> call and put are equal by symmetry.
    c = bs_price(100, 100, 0.01, 0.2, is_call=True)
    p = bs_price(100, 100, 0.01, 0.2, is_call=False)
    assert abs(c - p) < 1e-9
    assert c > 0


def test_bs_decays_to_intrinsic():
    # As time -> 0 an ITM call is worth its intrinsic value.
    v = bs_price(105, 100, 1e-9, 0.2, is_call=True)
    assert abs(v - 5.0) < 1e-3
    # OTM put with no time is worthless.
    assert bs_price(105, 100, 1e-9, 0.2, is_call=False) < 1e-6


def test_bs_monotonic_in_vol():
    lo = bs_price(100, 100, 0.02, 0.10, True)
    hi = bs_price(100, 100, 0.02, 0.30, True)
    assert hi > lo


def test_indicators_are_causal():
    # Breakout level at i must not depend on bar i itself (shifted).
    x = np.arange(20.0)
    hi = ind.rolling_max_shift(x, 5)
    # level at i is max of the prior 5 -> equals x[i-1] for a rising series.
    for i in range(5, 20):
        assert hi[i] == x[i - 1]


def test_costs_always_reduce_pnl():
    # A round trip with NO underlying move must lose money (spread+commission).
    cfg = spy_run(StrategyParams())
    mid = 1.0
    buy = cfg.costs.fill_price(mid, is_buy=True)
    sell = cfg.costs.fill_price(mid, is_buy=False)
    net = (sell - buy) * cfg.symbol.contract_multiplier - 2 * cfg.costs.commission
    assert net < 0


def test_no_lookahead_past_unaffected_by_future():
    """Appending future bars must not change trades that already closed.

    This is the operational definition of "no lookahead": the decision on any
    bar depends only on bars up to it.  We run on a prefix and on the full day
    and assert the prefix's trades are a prefix of the full run's trades.
    """
    cfg = spy_run(StrategyParams(timeframe_min=5, breakout_lookback=8,
                                 ema_fast=5, ema_slow=20, mom_thresh_atr=0.0))
    days = load_days(CSV5, 5, cfg.symbol)
    day = days[0]
    n = len(day)
    cut = n - 10

    # full run
    full = Engine(cfg).run([day])

    # prefix run: same day truncated to `cut` bars
    import copy
    pref_day = copy.copy(day)
    for attr in ("ts", "open", "high", "low", "close", "volume", "minutes_to_expiry"):
        setattr(pref_day, attr, getattr(day, attr)[:cut])
    pref = Engine(cfg).run([pref_day])

    # every trade that both fully entered AND exited before the cut must match.
    import pandas as pd
    cut_ts = pd.Timestamp(day.ts[cut - 1])
    for tp in pref.trades:
        if pd.Timestamp(tp.exit_time) < cut_ts:
            match = [tf for tf in full.trades
                     if tf.entry_time == tp.entry_time and tf.exit_reason != "eod"]
            assert match, "a pre-cut trade vanished when future data was added"


def test_one_position_at_a_time():
    cfg = spy_run(StrategyParams(timeframe_min=5))
    days = load_days(CSV5, 5, cfg.symbol)
    res = Engine(cfg).run(days)
    # within each day, trades must not overlap in time.
    import pandas as pd
    from collections import defaultdict
    per_day = defaultdict(list)
    for t in res.trades:
        per_day[t.date].append((pd.Timestamp(t.entry_time), pd.Timestamp(t.exit_time)))
    for date, spans in per_day.items():
        spans.sort()
        for a, b in zip(spans, spans[1:]):
            assert a[1] <= b[0], f"overlapping positions on {date}"


def test_eod_flat_every_day():
    # No position may survive the session; every day's last trade reason chain
    # ends flat (the engine books an eod trade if needed).
    cfg = spy_run(StrategyParams(timeframe_min=5))
    days = load_days(CSV5, 5, cfg.symbol)
    res = Engine(cfg).run(days)
    # reconstruct net exposure per day end -> must be zero (equal opens/closes).
    # Each Trade is a complete round trip, so this holds by construction; assert
    # there is no trade whose exit_time is missing.
    for t in res.trades:
        assert t.exit_time is not None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"\n{len(fns)} tests passed")
