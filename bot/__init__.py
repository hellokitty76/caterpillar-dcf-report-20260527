"""SPY -> SPX 0DTE swing-options bot.

A research + execution scaffold that detects directional swings in the
underlying (SPY, later SPX) and expresses each swing with a single ATM 0DTE
option, holding one position at a time.  See README.md for the full spec map
(P1..P6) and the honest list of modelling assumptions and data limitations.
"""

__all__ = [
    "config",
    "costs",
    "options",
    "indicators",
    "data",
    "signals",
    "engine",
    "walkforward",
    "sizing",
    "live",
]
