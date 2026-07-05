"""Bar-by-bar backtest engine -- the referee for the hard rules (§8).

Guarantees, by construction:
  * one position at a time (a new entry is impossible while `pos` is set);
  * no lookahead -- decisions use only closed bars, and fills happen on the
    NEXT bar's open (or the same close if entry_on_next_open is False);
  * every 0DTE position is flat by the session end (EOD gate);
  * spread + commission + slippage are charged on both legs, always.

P&L is per ONE contract; sizing.py scales it to the $500/day target.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import RunConfig
from .data import TradingDay
from .options import Pricer, atm_strike
from .signals import (ExitState, Features, LONG, SHORT, compute_features,
                      entry_signal, reversal_or_stop)


@dataclass
class Trade:
    date: str
    direction: int                # LONG / SHORT
    is_call: bool
    strike: float
    entry_time: object
    entry_underlying: float
    entry_prem_mid: float
    entry_fill: float             # premium paid (incl. spread+slippage)
    exit_time: object
    exit_underlying: float
    exit_prem_mid: float
    exit_fill: float              # premium received
    exit_reason: str
    iv: float
    net_pnl: float                # $ for ONE contract, after all costs

    @property
    def gross_pnl(self) -> float:
        return self.net_pnl_from(self.entry_prem_mid, self.exit_prem_mid, 0.0)

    @staticmethod
    def net_pnl_from(buy, sell, commission_roundtrip, mult=100):
        return (sell - buy) * mult - commission_roundtrip


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    days: int = 0

    # ---- aggregate metrics (per one contract) ----
    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def net_total(self) -> float:
        return sum(t.net_pnl for t in self.trades)

    @property
    def net_per_day(self) -> float:
        return self.net_total / self.days if self.days else 0.0

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.net_pnl > 0) / len(self.trades)

    @property
    def avg_net(self) -> float:
        return self.net_total / self.n if self.n else 0.0

    @property
    def profit_factor(self) -> float:
        gains = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        losses = -sum(t.net_pnl for t in self.trades if t.net_pnl < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    @property
    def max_drawdown(self) -> float:
        peak, dd = 0.0, 0.0
        eq = 0.0
        for t in self.trades:
            eq += t.net_pnl
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        return dd

    def summary(self) -> dict:
        return {
            "days": self.days,
            "trades": self.n,
            "trades_per_day": round(self.n / self.days, 2) if self.days else 0,
            "net_total": round(self.net_total, 2),
            "net_per_day": round(self.net_per_day, 2),
            "avg_net_per_trade": round(self.avg_net, 2),
            "win_rate": round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 2)
            if self.profit_factor != float("inf") else "inf",
            "max_drawdown": round(self.max_drawdown, 2),
        }


class Engine:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.pricer = Pricer(cfg.options)

    def run(self, days: list[TradingDay]) -> BacktestResult:
        result = BacktestResult(days=len(days))
        for day in days:
            self._run_day(day, result)
        return result

    def _run_day(self, day: TradingDay, result: BacktestResult) -> None:
        p = self.cfg.params
        f: Features = compute_features(day, p)
        iv = self.pricer.resolve_iv(day.realized_vol_annual)
        n = len(day)

        pos: dict | None = None
        state: ExitState | None = None
        pending: tuple | None = None    # ('enter', dir) | ('exit', reason)

        for i in range(n):
            # (1) execute whatever was decided on the previous bar, at this open
            if pending is not None:
                kind = pending[0]
                if kind == "enter" and pos is None:
                    pos, state = self._open(day, i, pending[1], iv, f,
                                            fill_underlying=day.open[i],
                                            fill_i=i)
                elif kind == "exit" and pos is not None:
                    self._close(day, i, pos, iv, result, pending[1],
                                fill_underlying=day.open[i], fill_i=i)
                    pos, state = None, None
                pending = None

            # (2) fold the now-complete bar i into the peak tracker
            if pos is not None:
                state.update_peak(day.high[i], day.low[i])

            # (3) decide on this bar's close
            t = day.ts[i]
            hh_mm = _as_time(t)
            if pos is not None:
                reason = self._exit_reason(day, i, pos, state, iv, hh_mm, last=i == n - 1)
                if reason == "eod":
                    # cannot carry 0DTE: flatten now at this close
                    self._close(day, i, pos, iv, result, reason,
                                fill_underlying=day.close[i], fill_i=i)
                    pos, state = None, None
                elif reason is not None:
                    pending = ("exit", reason)
                    if not p.entry_on_next_open:
                        self._close(day, i, pos, iv, result, reason,
                                    fill_underlying=day.close[i], fill_i=i)
                        pos, state, pending = None, None, None
            else:
                if hh_mm < p.eod_flat and i < n - 1:
                    sig = entry_signal(day, f, i, p)
                    if sig != 0:
                        if p.entry_on_next_open:
                            pending = ("enter", sig)
                        else:
                            pos, state = self._open(day, i, sig, iv, f,
                                                    fill_underlying=day.close[i],
                                                    fill_i=i)

        # safety net: if somehow still holding at the last bar, book it flat
        if pos is not None:
            self._close(day, n - 1, pos, iv, result, "eod",
                        fill_underlying=day.close[n - 1], fill_i=n - 1)

    # ------------------------------------------------------------------ #
    def _open(self, day, i, direction, iv, f, fill_underlying, fill_i):
        is_call = direction == LONG
        strike = atm_strike(fill_underlying)
        yrs = day.years_to_expiry(fill_i)
        mid = self.pricer.price(fill_underlying, strike, yrs, iv, is_call)
        fill = self.cfg.costs.fill_price(mid, is_buy=True)
        pos = dict(direction=direction, is_call=is_call, strike=strike,
                   entry_time=day.ts[fill_i], entry_underlying=fill_underlying,
                   entry_mid=mid, entry_fill=fill, iv=iv, date=day.date)
        # ATR frozen at the entry-decision bar (i), from precomputed features.
        state = ExitState(direction=direction, entry_underlying=fill_underlying,
                          atr_at_entry=float(f.atr[i]),
                          peak_underlying=fill_underlying)
        return pos, state

    def _close(self, day, i, pos, iv, result, reason, fill_underlying, fill_i):
        yrs = day.years_to_expiry(fill_i)
        mid = self.pricer.price(fill_underlying, pos["strike"], yrs, iv, pos["is_call"])
        fill = self.cfg.costs.fill_price(mid, is_buy=False)
        mult = self.cfg.symbol.contract_multiplier
        commission = self.cfg.costs.commission_dollars(1) * 2  # both legs
        net = (fill - pos["entry_fill"]) * mult - commission
        result.trades.append(Trade(
            date=pos["date"], direction=pos["direction"], is_call=pos["is_call"],
            strike=pos["strike"], entry_time=pos["entry_time"],
            entry_underlying=pos["entry_underlying"], entry_prem_mid=pos["entry_mid"],
            entry_fill=pos["entry_fill"], exit_time=day.ts[fill_i],
            exit_underlying=fill_underlying, exit_prem_mid=mid, exit_fill=fill,
            exit_reason=reason, iv=iv, net_pnl=net))

    def _exit_reason(self, day, i, pos, state, iv, hh_mm, last):
        if hh_mm >= self.cfg.params.eod_flat or last:
            return "eod"
        rs = reversal_or_stop(state, day.close[i], self.cfg.params)
        if rs is not None:
            return rs
        # hard option stop: premium bled past the tolerated fraction
        yrs = day.years_to_expiry(i)
        val = self.pricer.price(day.close[i], pos["strike"], yrs, iv, pos["is_call"])
        if val <= (1.0 - self.cfg.params.hard_option_stop) * pos["entry_fill"]:
            return "opt_stop"
        return None


def _as_time(ts):
    # ts may be a numpy datetime64 or pandas Timestamp
    import pandas as pd
    return pd.Timestamp(ts).time()
