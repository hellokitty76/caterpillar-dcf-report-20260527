"""ATM 0DTE option pricing -- the bridge from underlying path to option P&L.

Black-Scholes with r=q=0.  For a single position we only ever price two
things: the ATM premium at entry, and the same option's premium later in the
day (same strike, less time, new spot).  The difference, times the multiplier
and contract count, minus costs, is the trade P&L.
"""

from __future__ import annotations

import math

from .config import OptionModel

_SQRT_2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def bs_price(spot: float, strike: float, years: float, sigma: float,
             is_call: bool, rate: float = 0.0) -> float:
    """Black-Scholes European price (r=q=0 by default).

    Degenerates gracefully to intrinsic value as `years` or `sigma` -> 0,
    which is exactly the 0DTE end-of-life behaviour we want.
    """
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if years <= 0.0 or sigma <= 0.0 or spot <= 0.0:
        return intrinsic
    vol_t = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / vol_t
    d2 = d1 - vol_t
    if is_call:
        disc = strike * math.exp(-rate * years)
        return spot * _norm_cdf(d1) - disc * _norm_cdf(d2)
    disc = strike * math.exp(-rate * years)
    return disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(spot: float, strike: float, years: float, sigma: float,
             is_call: bool, rate: float = 0.0) -> float:
    """Option delta -- reported for context / sanity (ATM 0DTE ~ +-0.5)."""
    if years <= 0.0 or sigma <= 0.0 or spot <= 0.0:
        itm = (spot > strike) if is_call else (spot < strike)
        base = 1.0 if itm else 0.0
        return base if is_call else -base
    vol_t = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / vol_t
    return _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0


def atm_strike(spot: float, step: float = 1.0) -> float:
    """Nearest listed strike to spot.  SPY/SPX list $1 strikes near the money."""
    return round(spot / step) * step


class Pricer:
    """Prices the single ATM 0DTE option a position holds, over its life."""

    def __init__(self, model: OptionModel):
        self.m = model

    def resolve_iv(self, realized_vol_annual: float | None) -> float:
        """Turn a (per-day) realized-vol estimate into the IV we price with."""
        if self.m.iv_mode == "fixed" or realized_vol_annual is None:
            return max(self.m.iv_fixed, self.m.iv_floor)
        return max(realized_vol_annual * self.m.iv_scale, self.m.iv_floor)

    def price(self, spot: float, strike: float, years: float, iv: float,
              is_call: bool) -> float:
        years = max(years, self.m.min_years_to_expiry)
        return bs_price(spot, strike, years, iv, is_call, self.m.risk_free)

    def delta(self, spot: float, strike: float, years: float, iv: float,
              is_call: bool) -> float:
        years = max(years, self.m.min_years_to_expiry)
        return bs_delta(spot, strike, years, iv, is_call, self.m.risk_free)
