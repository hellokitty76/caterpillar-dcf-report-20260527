"""Data layer: load bars, restrict to RTH, resample, group by trading day.

Input is a CSV of the raw form produced by scripts/fetch_data.py:
    time (ISO-8601 UTC, e.g. 2026-07-02T13:30:00Z), open, high, low, close, volume

Everything downstream consumes `TradingDay` objects, which carry causal numpy
arrays plus the two things the option pricer needs per bar: minutes remaining
to the 16:00 expiry, and the day's realized-vol estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import SymbolConfig

_ET = ZoneInfo("America/New_York")
_MINUTES_PER_TRADING_DAY = 390          # 09:30-16:00
_TRADING_DAYS_PER_YEAR = 252


@dataclass
class TradingDay:
    """One session's worth of bars for one timeframe."""

    date: str                    # YYYY-MM-DD (US/Eastern)
    ts: np.ndarray               # pandas Timestamps (tz-aware, US/Eastern)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    minutes_to_expiry: np.ndarray  # minutes from each bar's open to 16:00 ET
    realized_vol_annual: float     # per-day annualized close-to-close vol

    def __len__(self) -> int:
        return len(self.close)

    def years_to_expiry(self, i: int) -> float:
        return max(self.minutes_to_expiry[i], 0.0) / (_MINUTES_PER_TRADING_DAY
                                                       * _TRADING_DAYS_PER_YEAR)


def _annualized_realized_vol(close: np.ndarray, timeframe_min: int) -> float:
    """Close-to-close realized vol for a single day, annualized.

    Thin days can produce a degenerate estimate; the OptionModel floor
    (config) protects the pricer downstream.
    """
    if len(close) < 3:
        return 0.0
    rets = np.diff(np.log(close))
    if rets.size == 0:
        return 0.0
    bars_per_day = _MINUTES_PER_TRADING_DAY / timeframe_min
    periods_per_year = _TRADING_DAYS_PER_YEAR * bars_per_day
    return float(np.std(rets, ddof=1) * np.sqrt(periods_per_year))


# Column-name synonyms seen in real intraday CSV exports.
_COL_SYNONYMS = {
    "open": ["open", "o", "openprice"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "c", "closeprice", "last"],
    "volume": ["volume", "v", "vol"],
}
# Unambiguous FULL datetime columns (carry both date and time).
_DT_FULL = ["timestamp", "datetime", "date_time", "date_time_utc"]
# Bare time-of-day columns -- only meaningful alongside a date column.
_TIME_OF_DAY = ["time", "timeofday", "clock"]
_DATE_ONLY = ["date", "day"]
# Last-resort single column (our own exports use "time" for a full ISO stamp).
_DT_FALLBACK = ["time", "t", "dt"]


def _pick(cols_lower: dict, names: list[str]) -> str | None:
    for n in names:
        if n in cols_lower:
            return cols_lower[n]
    return None


def _parse_single(raw: pd.Series, assume_tz: str) -> pd.Series:
    if pd.api.types.is_numeric_dtype(raw):
        return pd.to_datetime(raw, utc=True)            # epoch -> UTC
    return _localize(pd.to_datetime(raw, utc=False, format="mixed"), assume_tz)


def _parse_datetime(df: pd.DataFrame, assume_tz: str) -> pd.Series:
    """Build a tz-aware ET timestamp series from many possible layouts.

    Precedence (so a bare "Time" column can't masquerade as a full stamp):
      1. an explicit full datetime column (timestamp/datetime/...);
      2. a date column, combined with a time-of-day column if present;
      3. a fallback single column ("time"/"t"/"dt") holding a full ISO/epoch.
    Naive timestamps are localized with `assume_tz`, then all convert to ET.
    """
    cols_lower = {c.lower(): c for c in df.columns}

    full = _pick(cols_lower, _DT_FULL)
    if full is not None:
        ts = _parse_single(df[full], assume_tz)
    else:
        d = _pick(cols_lower, _DATE_ONLY)
        if d is not None:
            t = _pick(cols_lower, _TIME_OF_DAY)
            combo = df[d].astype(str) + (" " + df[t].astype(str) if t else "")
            ts = _localize(pd.to_datetime(combo, format="mixed"), assume_tz)
        else:
            single = _pick(cols_lower, _DT_FALLBACK)
            if single is None:
                raise ValueError(
                    "no recognizable datetime column; expected a full "
                    f"datetime {_DT_FULL + _DT_FALLBACK} or a date(+time) pair")
            ts = _parse_single(df[single], assume_tz)
    return ts.dt.tz_convert(_ET)


def _localize(parsed: pd.Series, assume_tz: str) -> pd.Series:
    if parsed.dt.tz is None:
        return parsed.dt.tz_localize(assume_tz)
    return parsed.dt.tz_convert("UTC")


def read_bars_csv(csv_path: str, assume_tz: str = "America/New_York"
                  ) -> pd.DataFrame:
    """Flexible reader -> canonical OHLCV frame indexed by ET timestamp.

    Accepts varied column names and datetime layouts so a 2024/2025 export
    from another vendor loads without hand-editing.  Naive timestamps are
    assumed to be in `assume_tz` (change it if your file is UTC-naive).
    """
    df = pd.read_csv(csv_path)
    cols_lower = {c.lower(): c for c in df.columns}
    ts = _parse_datetime(df, assume_tz)
    out = pd.DataFrame({"ts": ts})
    for canon, syns in _COL_SYNONYMS.items():
        src = _pick(cols_lower, syns)
        if src is None:
            if canon == "volume":
                out[canon] = 0.0          # volume is optional for the strategy
                continue
            raise ValueError(f"missing '{canon}' column (looked for {syns})")
        out[canon] = pd.to_numeric(df[src], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out.set_index("ts").sort_index()[
        ["open", "high", "low", "close", "volume"]]


def _load_frame(csv_path: str) -> pd.DataFrame:
    return read_bars_csv(csv_path)


def _restrict_rth(df: pd.DataFrame, symbol: SymbolConfig) -> pd.DataFrame:
    t = df.index.time
    mask = (t >= symbol.session_open) & (t < symbol.session_close)
    return df[mask]


def _resample(df: pd.DataFrame, timeframe_min: int) -> pd.DataFrame:
    if timeframe_min == 1:
        return df
    rule = f"{timeframe_min}min"
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    # label/closed='left' so a bar is stamped at its OPEN time -- essential for
    # correct minutes-to-expiry and for acting at the bar's open.
    out = df.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open"])
    return out


def load_days(csv_path: str, timeframe_min: int,
              symbol: SymbolConfig) -> list[TradingDay]:
    """Load a CSV into per-day, per-timeframe TradingDay objects."""
    df = _restrict_rth(_load_frame(csv_path), symbol)
    df = _resample(df, timeframe_min)
    days: list[TradingDay] = []
    for date, day_df in df.groupby(df.index.normalize()):
        if len(day_df) < 5:            # skip near-empty partial sessions
            continue
        close = day_df["close"].to_numpy(dtype=float)
        expiry = _expiry_timestamp(day_df.index[0], symbol.expiry)
        mte = np.array([(expiry - t).total_seconds() / 60.0 for t in day_df.index])
        days.append(TradingDay(
            date=str(date.date()),
            ts=day_df.index.to_numpy(),
            open=day_df["open"].to_numpy(dtype=float),
            high=day_df["high"].to_numpy(dtype=float),
            low=day_df["low"].to_numpy(dtype=float),
            close=close,
            volume=day_df["volume"].to_numpy(dtype=float),
            minutes_to_expiry=mte,
            realized_vol_annual=_annualized_realized_vol(close, timeframe_min),
        ))
    return days


def _expiry_timestamp(any_ts_that_day: pd.Timestamp, expiry: time) -> pd.Timestamp:
    return any_ts_that_day.normalize() + pd.Timedelta(
        hours=expiry.hour, minutes=expiry.minute)


def split_days(days: list[TradingDay], train_frac: float
               ) -> tuple[list[TradingDay], list[TradingDay]]:
    """Chronological train/test split (no shuffling -- time matters)."""
    k = max(1, int(round(len(days) * train_frac)))
    k = min(k, len(days) - 1)          # always leave >=1 test day
    return days[:k], days[k:]
