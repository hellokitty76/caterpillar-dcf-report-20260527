"""Indicators as pure functions over numpy arrays.

Every series is causal: the value at index i uses only bars 0..i.  Breakout
levels are explicitly shifted so that the level a bar is tested against is
formed from *prior* bars only -- no bar breaks out over its own high.  This is
the mechanical guarantee behind the no-lookahead rule (§8); engine.py adds the
second guarantee (acting on the next bar).
"""

from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average, seeded with the first value (causal)."""
    if span <= 1:
        return values.astype(float).copy()
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]
    a = high - low
    b = np.abs(high - prev_close)
    c = np.abs(low - prev_close)
    return np.maximum(a, np.maximum(b, c))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int) -> np.ndarray:
    """Wilder-style ATR via an EMA of true range (causal)."""
    tr = true_range(high, low, close)
    return ema(tr, period)


def rolling_max_shift(values: np.ndarray, window: int) -> np.ndarray:
    """Highest of the PRIOR `window` bars (value at i excludes bar i).

    NaN for the first `window` bars where a full prior window is unavailable.
    """
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(window, n):
        out[i] = np.max(values[i - window:i])
    return out


def rolling_min_shift(values: np.ndarray, window: int) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(window, n):
        out[i] = np.min(values[i - window:i])
    return out


def roc(values: np.ndarray, lookback: int) -> np.ndarray:
    """Absolute price change over the last `lookback` bars (causal)."""
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(lookback, n):
        out[i] = values[i] - values[i - lookback]
    return out
