"""Position sizing -> the $500/day target (§5).

The engine reports P&L for ONE contract.  The daily target is hit by trading
`contracts` of them.  Two independent ceilings apply and we take the binding
one:

  1. Target ceiling  : contracts to make the *out-of-sample* net $/day reach
                        the goal.  Uses the OOS edge, never the in-sample one.
  2. Risk ceiling     : contracts small enough that a bad day's realistic loss
                        stays inside the risk budget you set.

If the target ceiling exceeds the risk ceiling, the honest answer is "this edge
cannot fund $500/day at your risk tolerance" -- the function says so rather
than quietly sizing you into ruin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .engine import BacktestResult


@dataclass
class SizingResult:
    feasible: bool
    contracts: int
    target_daily: float
    oos_net_per_day_1lot: float
    expected_net_per_day: float
    worst_day_loss_1lot: float
    risk_budget_daily: float
    binding_constraint: str
    notes: str

    def as_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


def _worst_day_loss_1lot(res: BacktestResult) -> float:
    """Largest single-day net loss for one contract (empirical, OOS)."""
    by_day: dict[str, float] = {}
    for t in res.trades:
        by_day[t.date] = by_day.get(t.date, 0.0) + t.net_pnl
    if not by_day:
        return 0.0
    worst_day = min(by_day.values())
    return -worst_day if worst_day < 0 else 0.0


def size_for_target(oos: BacktestResult, target_daily: float = 500.0,
                    risk_budget_daily: float = 1000.0) -> SizingResult:
    edge = oos.net_per_day                     # net $/day for one contract, OOS
    worst = _worst_day_loss_1lot(oos)

    if edge <= 0:
        return SizingResult(
            feasible=False, contracts=0, target_daily=target_daily,
            oos_net_per_day_1lot=edge, expected_net_per_day=0.0,
            worst_day_loss_1lot=worst, risk_budget_daily=risk_budget_daily,
            binding_constraint="edge",
            notes="Out-of-sample edge is <= 0. Do not size up; the strategy is "
                  "not validated to make money on unseen data with these costs.")

    target_lots = math.ceil(target_daily / edge)
    risk_lots = math.floor(risk_budget_daily / worst) if worst > 0 else target_lots
    contracts = min(target_lots, risk_lots)
    binding = "target" if target_lots <= risk_lots else "risk"
    feasible = contracts >= target_lots

    notes = (f"To reach ${target_daily:.0f}/day at the OOS edge of "
             f"${edge:.2f}/contract/day you need {target_lots} contracts; "
             f"the risk budget allows {risk_lots}. ")
    if not feasible:
        notes += ("Risk budget binds first -- raise the budget, lower the "
                  "target, or improve the edge before trading this size.")
    return SizingResult(
        feasible=feasible, contracts=max(contracts, 0), target_daily=target_daily,
        oos_net_per_day_1lot=edge, expected_net_per_day=edge * contracts,
        worst_day_loss_1lot=worst, risk_budget_daily=risk_budget_daily,
        binding_constraint=binding, notes=notes)
