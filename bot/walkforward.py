"""Walk-forward parameter search (§6).

The rule the spec insists on: a parameter set only counts if it still works on
data it was NOT fit on.  So we never report a single in-sample number.  For
each timeframe we roll an anchored (expanding) window forward: fit on the past,
trade the next unseen block, and stitch those out-of-sample blocks into one
honest OOS track record.  The timeframe itself is a searched dimension.

Costs are inside every backtest (engine.py), so every number here is net.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

from .config import RunConfig, StrategyParams
from .data import TradingDay, load_days
from .engine import BacktestResult, Engine


# --------------------------------------------------------------------------- #
# Search space                                                                  #
# --------------------------------------------------------------------------- #
DEFAULT_GRID = {
    "breakout_lookback": [8, 12, 20],
    "ema_pair": [(5, 20), (9, 21), (9, 34)],
    "mom_thresh_atr": [0.0, 0.10, 0.25],
    "trail_atr": [1.0, 1.5, 2.5],
    "stop_atr": [0.75, 1.25],
}


def _expand_grid(base: StrategyParams, grid: dict) -> list[StrategyParams]:
    keys = list(grid.keys())
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        kw = dict(zip(keys, values))
        ema_fast, ema_slow = kw.pop("ema_pair")
        combos.append(replace(base, ema_fast=ema_fast, ema_slow=ema_slow, **kw))
    return combos


# --------------------------------------------------------------------------- #
# Objective: what "best on train" means                                         #
# --------------------------------------------------------------------------- #
def train_score(res: BacktestResult, min_trades: int) -> float:
    """Rank in-sample candidates.

    Require a minimum trade count so we don't crown a params set that only
    fired once or twice.  Among the rest, maximise net $/day but tilt toward
    robustness (profit factor) so a single lucky trade can't win.
    """
    if res.n < min_trades or res.days == 0:
        return float("-inf")
    pf = res.profit_factor
    pf = 3.0 if pf == float("inf") else min(pf, 3.0)
    return res.net_per_day * (0.5 + 0.5 * min(pf, 2.0) / 2.0)


# --------------------------------------------------------------------------- #
# Single grid search on a fixed train set                                       #
# --------------------------------------------------------------------------- #
@dataclass
class SearchOutcome:
    params: StrategyParams
    train: BacktestResult
    score: float


def grid_search(cfg: RunConfig, train_days: list[TradingDay], grid: dict,
                min_trades: int) -> SearchOutcome:
    best: SearchOutcome | None = None
    for params in _expand_grid(cfg.params, grid):
        res = Engine(cfg.with_params(params)).run(train_days)
        s = train_score(res, min_trades)
        if best is None or s > best.score:
            best = SearchOutcome(params=params, train=res, score=s)
    return best


# --------------------------------------------------------------------------- #
# Anchored walk-forward over one timeframe                                      #
# --------------------------------------------------------------------------- #
@dataclass
class Fold:
    train_days: int
    test_dates: list[str]
    params: StrategyParams
    train: dict
    test: dict


@dataclass
class WalkForwardResult:
    timeframe_min: int
    folds: list[Fold]
    oos: BacktestResult          # concatenation of every test block
    def summary(self) -> dict:
        return {"timeframe_min": self.timeframe_min,
                "oos": self.oos.summary(),
                "n_folds": len(self.folds)}


def walk_forward(cfg: RunConfig, days: list[TradingDay], grid: dict,
                 initial_train: int | None = None, test_win: int = 2,
                 min_trades_per_fold: int = 3) -> WalkForwardResult:
    n = len(days)
    if initial_train is None:
        initial_train = max(5, n // 2)
    folds: list[Fold] = []
    oos = BacktestResult(days=0)

    start = initial_train
    while start < n:
        train = days[:start]
        test = days[start:start + test_win]
        if not test:
            break
        outcome = grid_search(cfg, train, grid, min_trades_per_fold)
        test_res = Engine(cfg.with_params(outcome.params)).run(test)
        # stitch OOS
        oos.trades.extend(test_res.trades)
        oos.days += test_res.days
        folds.append(Fold(
            train_days=len(train),
            test_dates=[d.date for d in test],
            params=outcome.params,
            train=outcome.train.summary(),
            test=test_res.summary(),
        ))
        start += test_win

    return WalkForwardResult(timeframe_min=cfg.params.timeframe_min,
                             folds=folds, oos=oos)


# --------------------------------------------------------------------------- #
# Timeframe search: run the walk-forward per timeframe, compare OOS             #
# --------------------------------------------------------------------------- #
@dataclass
class TimeframeCandidate:
    timeframe_min: int
    csv_path: str          # source CSV (native or 1-min to be resampled)


def search_timeframes(base_cfg: RunConfig, candidates: list[TimeframeCandidate],
                      grid: dict = None, **wf_kwargs) -> dict:
    grid = grid or DEFAULT_GRID
    results: dict[int, WalkForwardResult] = {}
    for cand in candidates:
        params = replace(base_cfg.params, timeframe_min=cand.timeframe_min)
        cfg = base_cfg.with_params(params)
        days = load_days(cand.csv_path, cand.timeframe_min, cfg.symbol)
        if len(days) < 3:
            continue
        results[cand.timeframe_min] = walk_forward(cfg, days, grid, **wf_kwargs)

    # rank timeframes by OOS net/day, but only those with a real OOS sample
    ranked = sorted(
        results.values(),
        key=lambda r: (r.oos.n >= 4, r.oos.net_per_day),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    return {"per_timeframe": results, "best": best}
