"""Real-time monitoring skeleton (P1).

This is the execution shell the backtested logic drops into for live/paper
trading.  It intentionally does NOT place real orders on its own -- the IBKR
wiring is documented and stubbed behind an explicit, off-by-default broker so
that running this file can never fire a live trade by accident.

Design:
  * a DataFeed yields bars one at a time (ReplayFeed for dry-runs off a CSV;
    IbkrFeed is the documented live adapter);
  * LiveMonitor keeps a growing intraday buffer, reuses the SAME signal/exit
    code as the backtest (bot.signals), and enforces the one-position rule;
  * a Broker receives intents.  PaperBroker prices fills with the same model
    as the backtest and logs them; IbkrBroker is where create_order_instruction
    would go, guarded so it stays a stub unless a human wires and arms it.

Because it shares bot.signals/bot.options with the engine, the live decisions
match the research logic by construction -- no second, drifting implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Iterator, Protocol

import numpy as np

from .config import RunConfig
from .data import TradingDay, load_days
from .options import Pricer, atm_strike
from .signals import (ExitState, LONG, compute_features, entry_signal,
                      reversal_or_stop)


# --------------------------------------------------------------------------- #
# Bars in, from any source                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class LiveBar:
    ts: object
    open: float
    high: float
    low: float
    close: float
    volume: float
    minutes_to_expiry: float


class DataFeed(Protocol):
    def __iter__(self) -> Iterator[LiveBar]: ...


class ReplayFeed:
    """Replays a TradingDay bar-by-bar -- for dry-running the live path."""

    def __init__(self, day: TradingDay):
        self.day = day

    def __iter__(self) -> Iterator[LiveBar]:
        d = self.day
        for i in range(len(d)):
            yield LiveBar(d.ts[i], d.open[i], d.high[i], d.low[i], d.close[i],
                          d.volume[i], d.minutes_to_expiry[i])


class IbkrFeed:
    """Live adapter (documented stub).

    In production this polls IBKR for the latest completed bar via the MCP tool
    `get_price_history` (contract_id for SPY/SPX, step matching the timeframe,
    outside_rth=false) and yields the newest bar once per timeframe interval.
    Left unimplemented on purpose so importing this module never opens a socket.
    """

    def __iter__(self):
        raise NotImplementedError(
            "Wire to IBKR get_price_history polling before live use.")


# --------------------------------------------------------------------------- #
# Brokers                                                                        #
# --------------------------------------------------------------------------- #
@dataclass
class OrderIntent:
    action: str          # "BUY_TO_OPEN" | "SELL_TO_CLOSE"
    right: str           # "C" | "P"
    strike: float
    contracts: int
    reason: str
    ts: object
    ref_underlying: float


class Broker(Protocol):
    def send(self, intent: OrderIntent, premium_mid: float) -> float: ...


@dataclass
class PaperBroker:
    cfg: RunConfig
    log: list = field(default_factory=list)

    def send(self, intent: OrderIntent, premium_mid: float) -> float:
        is_buy = intent.action == "BUY_TO_OPEN"
        fill = self.cfg.costs.fill_price(premium_mid, is_buy=is_buy)
        self.log.append((intent, fill))
        return fill


class IbkrBroker:
    """Live order placement (documented stub -- disabled by default).

    A real implementation resolves the 0DTE contract via get_option_parameters
    -> get_option_data (ATM strike), then submits with create_order_instruction.
    It is deliberately inert unless `armed=True` AND a human has reviewed it.
    """

    def __init__(self, armed: bool = False):
        self.armed = armed

    def send(self, intent: OrderIntent, premium_mid: float) -> float:
        if not self.armed:
            raise RuntimeError("IbkrBroker is not armed; refusing to trade live.")
        raise NotImplementedError(
            "Implement create_order_instruction wiring, then arm explicitly.")


# --------------------------------------------------------------------------- #
# The monitor                                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class MonitorState:
    in_position: bool = False
    direction: int = 0
    is_call: bool = False
    strike: float = 0.0
    entry_fill: float = 0.0
    exit_state: ExitState | None = None


class LiveMonitor:
    """One trading day's live loop.  Enforces the one-position hard rule."""

    def __init__(self, cfg: RunConfig, broker: Broker):
        self.cfg = cfg
        self.broker = broker
        self.pricer = Pricer(cfg.options)
        self.state = MonitorState()
        self._buf = {k: [] for k in ("ts", "o", "h", "l", "c", "v", "mte")}
        self._iv: float | None = None

    def set_day_iv(self, realized_vol_annual: float | None) -> None:
        self._iv = self.pricer.resolve_iv(realized_vol_annual)

    def on_bar(self, bar: LiveBar) -> None:
        for k, val in zip(("ts", "o", "h", "l", "c", "v", "mte"),
                          (bar.ts, bar.open, bar.high, bar.low, bar.close,
                           bar.volume, bar.minutes_to_expiry)):
            self._buf[k].append(val)
        i = len(self._buf["c"]) - 1
        if self._iv is None:
            self._iv = self.pricer.resolve_iv(None)

        day = self._buffer_as_day()
        p = self.cfg.params
        yrs = max(bar.minutes_to_expiry, 0.0) / (390.0 * 252.0)

        # --- manage an open position first (exits take priority) ---
        if self.state.in_position:
            self.state.exit_state.update_peak(bar.high, bar.low)
            reason = self._exit_reason(day, i, bar, yrs)
            if reason:
                self._exit(bar, yrs, reason)
            return

        # --- otherwise look for an entry (respect EOD lockout) ---
        if _t(bar.ts) >= p.eod_flat:
            return
        f = compute_features(day, p)
        sig = entry_signal(day, f, i, p)
        if sig != 0:
            self._enter(bar, yrs, sig, float(f.atr[i]))

    # ------------------------------------------------------------------ #
    def _enter(self, bar, yrs, direction, atr_now):
        is_call = direction == LONG
        strike = atm_strike(bar.close)
        mid = self.pricer.price(bar.close, strike, yrs, self._iv, is_call)
        intent = OrderIntent("BUY_TO_OPEN", "C" if is_call else "P", strike, 1,
                             "entry", bar.ts, bar.close)
        fill = self.broker.send(intent, mid)
        self.state = MonitorState(
            in_position=True, direction=direction, is_call=is_call, strike=strike,
            entry_fill=fill,
            exit_state=ExitState(direction, bar.close, atr_now, bar.close))

    def _exit(self, bar, yrs, reason):
        s = self.state
        mid = self.pricer.price(bar.close, s.strike, yrs, self._iv, s.is_call)
        intent = OrderIntent("SELL_TO_CLOSE", "C" if s.is_call else "P", s.strike,
                             1, reason, bar.ts, bar.close)
        self.broker.send(intent, mid)
        self.state = MonitorState()

    def _exit_reason(self, day, i, bar, yrs):
        p = self.cfg.params
        if _t(bar.ts) >= p.eod_flat:
            return "eod"
        rs = reversal_or_stop(self.state.exit_state, bar.close, p)
        if rs:
            return rs
        val = self.pricer.price(bar.close, self.state.strike, yrs, self._iv,
                                self.state.is_call)
        if val <= (1.0 - p.hard_option_stop) * self.state.entry_fill:
            return "opt_stop"
        return None

    def _buffer_as_day(self) -> TradingDay:
        b = self._buf
        return TradingDay(
            date=str(_t(b["ts"][0])), ts=np.array(b["ts"]),
            open=np.array(b["o"], float), high=np.array(b["h"], float),
            low=np.array(b["l"], float), close=np.array(b["c"], float),
            volume=np.array(b["v"], float),
            minutes_to_expiry=np.array(b["mte"], float),
            realized_vol_annual=0.0)


def _t(ts) -> time:
    import pandas as pd
    return pd.Timestamp(ts).time()


def dry_run(cfg: RunConfig, csv_path: str) -> list:
    """Replay a CSV through the live monitor with a paper broker."""
    broker = PaperBroker(cfg)
    days = load_days(csv_path, cfg.params.timeframe_min, cfg.symbol)
    for day in days:
        mon = LiveMonitor(cfg, broker)
        mon.set_day_iv(day.realized_vol_annual)
        for bar in ReplayFeed(day):
            mon.on_bar(bar)
    return broker.log
