"""Entry detection (§3) and the reversal/stop test used by exits (§4).

Features are all causal (see indicators.py).  Entry fires when a swing is
*starting*: price breaks the prior N-bar extreme, in the direction of the
short-term EMA trend, with enough momentum to not be noise.  The exit test
here is the stateful part of §4 (confirmed reversal + stop); the engine owns
the position state and the EOD/hard-option-stop gates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import indicators as ind
from .config import StrategyParams
from .data import TradingDay

LONG, FLAT, SHORT = 1, 0, -1


@dataclass
class Features:
    ema_fast: np.ndarray
    ema_slow: np.ndarray
    atr: np.ndarray
    brk_high: np.ndarray     # prior N-bar high (shifted, causal)
    brk_low: np.ndarray      # prior N-bar low (shifted, causal)
    roc: np.ndarray          # price change over mom_lookback bars


def compute_features(day: TradingDay, p: StrategyParams) -> Features:
    return Features(
        ema_fast=ind.ema(day.close, p.ema_fast),
        ema_slow=ind.ema(day.close, p.ema_slow),
        atr=ind.atr(day.high, day.low, day.close, p.atr_period),
        brk_high=ind.rolling_max_shift(day.high, p.breakout_lookback),
        brk_low=ind.rolling_min_shift(day.low, p.breakout_lookback),
        roc=ind.roc(day.close, p.mom_lookback),
    )


def entry_signal(day: TradingDay, f: Features, i: int, p: StrategyParams) -> int:
    """Direction to open at bar i's close, or FLAT.  Decided on closed data only."""
    a = f.atr[i]
    if not np.isfinite(a) or a <= 0:
        return FLAT
    if not (np.isfinite(f.brk_high[i]) and np.isfinite(f.brk_low[i])
            and np.isfinite(f.roc[i])):
        return FLAT

    c = day.close[i]
    mom = p.mom_thresh_atr * a
    up_trend = f.ema_fast[i] > f.ema_slow[i]
    dn_trend = f.ema_fast[i] < f.ema_slow[i]

    long_ok = up_trend and c > f.brk_high[i] and f.roc[i] >= mom
    short_ok = dn_trend and c < f.brk_low[i] and (-f.roc[i]) >= mom

    if long_ok and not short_ok:
        return LONG
    if short_ok and not long_ok:
        return SHORT
    return FLAT


@dataclass
class ExitState:
    """Mutable tracking for the open position, updated each bar by the engine."""

    direction: int            # LONG or SHORT
    entry_underlying: float
    atr_at_entry: float
    peak_underlying: float    # best favorable underlying level since entry

    def update_peak(self, high: float, low: float) -> None:
        if self.direction == LONG:
            self.peak_underlying = max(self.peak_underlying, high)
        else:
            self.peak_underlying = min(self.peak_underlying, low)


def reversal_or_stop(state: ExitState, close: float, p: StrategyParams
                     ) -> str | None:
    """Return 'reversal', 'stop', or None based on the underlying at this close.

    - reversal: gave back `trail_atr` ATRs from the best level reached (we rode
      the body of the swing and are now exiting near -- not at -- the peak).
    - stop: moved `stop_atr` ATRs against the entry (the swing never developed).
    """
    a = state.atr_at_entry
    if a <= 0:
        return None
    if state.direction == LONG:
        if close <= state.entry_underlying - p.stop_atr * a:
            return "stop"
        if close <= state.peak_underlying - p.trail_atr * a:
            return "reversal"
    else:
        if close >= state.entry_underlying + p.stop_atr * a:
            return "stop"
        if close >= state.peak_underlying + p.trail_atr * a:
            return "reversal"
    return None
