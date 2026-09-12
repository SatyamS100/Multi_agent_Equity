# data_fetch_utils.py
# ─────────────────────────────────────────────────────────────────────────────
# SHARED FAIL-LOUD GUARD — used by every data-fetch agent
# (stocktwits_agent.py, fundamentals.py, search_reddit_agent.py)
#
# Why this exists as a shared module instead of one-off code per agent:
#   All three data-fetch agents loop over the stock universe and can fail
#   per-ticker (network error, API block, missing data). A single ticker
#   failing is normal and handled locally. But if MOST of the universe
#   fails, that's a systemic problem (blocked, rate-limited, API changed)
#   and the agent should raise instead of quietly handing the scorer a
#   universe of placeholder/neutral data that looks like a real signal.
#
#   This was originally implemented once, inline, in stocktwits_agent.py
#   (see BUGS.md Phase 0 #2). Phase 1 extends the same guard to
#   fundamentals.py and search_reddit_agent.py — pulling it into one shared
#   function keeps the threshold and the error message format consistent
#   across all three instead of three slightly-different copies drifting
#   apart over time.
# ─────────────────────────────────────────────────────────────────────────────

from typing import List

# If more than this fraction of the universe fails, something is broken
# upstream (blocked, rate-limited, API change) — fail loudly instead of
# silently feeding the scorer a universe of placeholder/neutral signals.
MAX_FAILURE_RATIO = 0.5


class DataFetchError(RuntimeError):
    """Raised when a data-fetch agent fails for most of the stock universe."""


def raise_if_too_many_failed(
    source: str,
    failed_tickers: List[str],
    universe_size: int,
    max_ratio: float = MAX_FAILURE_RATIO,
) -> None:
    """
    Raises DataFetchError if the failure ratio for this run exceeds max_ratio.

    Args:
        source:         Human-readable name of the data source, for the
                         error message (e.g. "StockTwits", "yfinance
                         fundamentals", "Reddit search").
        failed_tickers: Tickers that failed to fetch this run.
        universe_size:  Total tickers attempted.
        max_ratio:      Failure fraction above which we abort (default 0.5).
    """
    if universe_size == 0:
        return

    ratio = len(failed_tickers) / universe_size
    if ratio > max_ratio:
        raise DataFetchError(
            f"{source} data collection failed for {len(failed_tickers)}/"
            f"{universe_size} tickers ({ratio:.0%}): {failed_tickers}. "
            f"Aborting rather than scoring on incomplete/placeholder data."
        )
