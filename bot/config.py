"""Configuration dataclasses for the swing-options bot.

Everything that a search or a live run needs to be told is a field here.
Nothing in the rest of the codebase hard-codes a symbol, a cost, or a
threshold -- it all flows from these objects, which is what makes the SPY ->
SPX port (P6) a config change rather than a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import time


# --------------------------------------------------------------------------- #
# Instrument                                                                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SymbolConfig:
    """Static facts about the traded instrument and its 0DTE option."""

    symbol: str = "SPY"
    # Dollars of P&L per 1.00 of option premium per contract.
    # Equity/ETF and index options are both 100.
    contract_multiplier: int = 100
    # Regular-trading-hours session in US/Eastern.
    session_open: time = time(9, 30)
    session_close: time = time(16, 0)
    # 0DTE options expire at the session close.
    expiry: time = time(16, 0)
    # Minimum option price tick, used only for reporting / rounding.
    option_tick: float = 0.01
    # Is the option cash-settled European (SPX) vs American (SPY)?  The pricing
    # model is Black-Scholes either way; this only affects narrative/notes.
    european: bool = False


SPY = SymbolConfig(symbol="SPY", contract_multiplier=100, european=False)

# SPX cash-settled index options (SPXW dailies are the 0DTE series).  Notional
# per contract is ~10x SPY, so far fewer contracts are needed for the same
# dollar target -- see sizing.py.  Costs differ too (see CostModel presets).
SPX = SymbolConfig(symbol="SPX", contract_multiplier=100, european=True)


# --------------------------------------------------------------------------- #
# Costs (applied on BOTH legs of every round trip -- never optional)            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostModel:
    """Spread + commission + slippage, charged on entry and on exit.

    Option premia are quoted per share; a contract is `contract_multiplier`
    shares.  `half_spread` and `slippage` are expressed in premium points
    (i.e. per share); `commission` is dollars per contract.
    """

    half_spread: float = 0.02       # half the bid/ask, premium points
    slippage: float = 0.005         # adverse fill beyond the touch, premium points
    commission: float = 0.65        # $ per contract, per leg

    def fill_price(self, mid: float, is_buy: bool) -> float:
        """Return the realistic fill premium given a mid quote.

        Buys pay up (mid + half_spread + slippage); sells receive less.
        Fills are floored at zero -- an option premium cannot go negative.
        """
        edge = self.half_spread + self.slippage
        px = mid + edge if is_buy else mid - edge
        return max(px, 0.0)

    def commission_dollars(self, contracts: int) -> float:
        return self.commission * contracts


# IBKR-ish retail defaults.  SPX spreads are wider in points but the strategy
# still nets more per contract because notional is 10x; tune with real quotes.
COSTS_SPY = CostModel(half_spread=0.02, slippage=0.005, commission=0.65)
COSTS_SPX = CostModel(half_spread=0.25, slippage=0.05, commission=1.00)


# --------------------------------------------------------------------------- #
# Option pricing (how underlying moves become option P&L)                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OptionModel:
    """Assumptions used to translate an underlying path into option premium.

    We do NOT have historical intraday 0DTE option quotes, so entry/exit
    premia are priced with Black-Scholes (r=q=0) using the live underlying,
    the ATM strike, the *remaining* time to the 16:00 expiry, and an implied
    vol.  IV is estimated from the day's realized volatility (data-driven) and
    floored, or fixed.  This captures the two things that matter for a 0DTE
    swing trade: convex payoff on the move, and theta bleed while you hold.
    See README for why this is a defensible approximation and where it is
    optimistic/pessimistic.
    """

    iv_mode: str = "realized"       # "realized" | "fixed"
    iv_fixed: float = 0.13          # annualized, used when iv_mode == "fixed"
    iv_floor: float = 0.08          # annualized floor for the realized estimate
    iv_scale: float = 1.15          # realized -> implied multiplier (IV usually > RV)
    risk_free: float = 0.0
    # Guard so time-to-expiry never hits exactly zero (numerical safety).
    min_years_to_expiry: float = 1.0 / (365.0 * 24.0 * 60.0 * 2.0)  # 30s


# --------------------------------------------------------------------------- #
# Strategy parameters (the things §6 searches for)                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategyParams:
    """Entry/exit parameters.  Walk-forward searches this space (walkforward.py)."""

    timeframe_min: int = 5          # bar size in minutes: 1 | 2 | 3 | 5

    # --- entry (§3): breakout in the direction of the short-term trend ---
    atr_period: int = 14
    breakout_lookback: int = 12     # N-bar high/low breakout
    ema_fast: int = 9
    ema_slow: int = 21
    mom_lookback: int = 3           # rate-of-change window
    mom_thresh_atr: float = 0.10    # ROC must exceed this * ATR to count as a start

    # --- exit (§4) ---
    trail_atr: float = 1.5          # give-back from peak (confirmed reversal)
    stop_atr: float = 1.0           # adverse excursion from entry (stop loss)
    hard_option_stop: float = 0.60  # also bail if option loses >= this fraction
    eod_flat: time = time(15, 55)   # 0DTE must be flat by here (§4.3)

    # Fill convention: act on the NEXT bar's open after a signal prints on a
    # bar close.  This is the honest, no-lookahead choice (§8).
    entry_on_next_open: bool = True

    def resampled_from_1min(self) -> bool:
        return self.timeframe_min != 1


@dataclass(frozen=True)
class RunConfig:
    """Everything a backtest/live run needs, bundled."""

    symbol: SymbolConfig = field(default_factory=lambda: SPY)
    costs: CostModel = field(default_factory=lambda: COSTS_SPY)
    options: OptionModel = field(default_factory=OptionModel)
    params: StrategyParams = field(default_factory=StrategyParams)

    def with_params(self, params: StrategyParams) -> "RunConfig":
        return replace(self, params=params)


# Convenience presets -------------------------------------------------------- #
def spy_run(params: StrategyParams | None = None) -> RunConfig:
    return RunConfig(symbol=SPY, costs=COSTS_SPY, options=OptionModel(),
                     params=params or StrategyParams())


def spx_run(params: StrategyParams | None = None) -> RunConfig:
    return RunConfig(symbol=SPX, costs=COSTS_SPX, options=OptionModel(),
                     params=params or StrategyParams())
