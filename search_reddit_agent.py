import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

import praw
from prawcore.exceptions import PrawcoreException

from config import (
    STOCK_UNIVERSE,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
)
from data_fetch_utils import raise_if_too_many_failed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Subreddits searched per ticker, combined into one PRAW multi-subreddit
# query rather than three separate API calls.
SUBREDDITS = "wallstreetbets+stocks+investing"
POSTS_PER_TICKER = 25
SEARCH_TIME_FILTER = "week"


def get_reddit_client() -> praw.Reddit:
    """
    Builds a read-only PRAW client from REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET
    (config.py, env-overridable via .env). Raises immediately if credentials
    are missing, rather than failing deep inside the fetch loop with an
    opaque prawcore auth error — same fail-fast pattern as
    graph.get_llm_client() for GROQ_API_KEY.
    """
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise RuntimeError(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set. Create a "
            "read-only 'script' app at https://www.reddit.com/prefs/apps, "
            "then copy .env.example to .env and fill in the Reddit "
            "credentials."
        )
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )
    reddit.read_only = True
    return reddit


def fetch_reddit_sentiment_via_search(universe: List[str] = STOCK_UNIVERSE) -> Dict[str, dict]:
    """
    Fetches real Reddit posts mentioning each ticker from r/wallstreetbets,
    r/stocks, and r/investing via the official Reddit API (PRAW).

    Phase 6 replacement for the DuckDuckGo-search-based version (Phase
    0-5): that approach avoided needing Reddit credentials, but Phase 5's
    live run found DuckDuckGo's anti-scraping defenses had tightened to the
    point of near-total failure (24/24, then 23/24 tickers, across two
    consecutive live runs — see BUGS.md issue #23). This trades the
    credential requirement back for a stable, ToS-compliant, official API.
    It also means `avg_post_score` and the 24h/7d mention split are now
    real Reddit data (upvotes, real post timestamps) instead of a mocked
    constant and an unscoped-search-count heuristic — the DuckDuckGo
    version could never provide either.

    Raises:
        DataFetchError (from data_fetch_utils): if more than
            MAX_FAILURE_RATIO of the universe raised a search exception.
            Note this tracks actual search *errors* (Reddit API down/rate-
            limited), not tickers that legitimately have zero Reddit
            mentions — a quiet ticker is a real (if boring) signal, not a
            failure.
    """
    reddit = get_reddit_client()
    subreddit = reddit.subreddit(SUBREDDITS)
    results = {}
    failed_tickers = []

    for ticker in universe:
        logger.info(f"Searching Reddit for {ticker} via PRAW...")

        posts = []
        try:
            for submission in subreddit.search(
                f'"{ticker}"',
                time_filter=SEARCH_TIME_FILTER,
                sort="new",
                limit=POSTS_PER_TICKER,
            ):
                posts.append({
                    "title": submission.title,
                    "text": (submission.selftext or "")[:200],
                    "url": f"https://reddit.com{submission.permalink}",
                    "score": submission.score,
                    "subreddit": submission.subreddit.display_name.lower(),
                    "created_utc": submission.created_utc,
                })
        except PrawcoreException as e:
            logger.error(f"Search failed for {ticker}: {e}")
            failed_tickers.append(ticker)
            time.sleep(1.0)
            continue

        now = datetime.now(timezone.utc).timestamp()
        mentions_24h = sum(1 for p in posts if now - p["created_utc"] <= 86400)
        mentions_7d = len(posts)  # search is already scoped to the last week

        # Same momentum/spike formulas as the pre-Phase-6 implementation —
        # only the underlying data source changed, not the scoring shape.
        momentum = min(mentions_24h / 5.0, 1.0)
        spike = mentions_24h >= 8

        avg_score = (sum(p["score"] for p in posts) / len(posts)) if posts else 0.0

        breakdown = defaultdict(int)
        for p in posts:
            breakdown[p["subreddit"]] += 1

        top_posts = sorted(posts, key=lambda p: p["score"], reverse=True)[:5]

        results[ticker] = {
            "ticker":              ticker,
            "total_mentions":      mentions_7d,
            "mentions_24h":        mentions_24h,
            "mentions_7d":         mentions_7d,
            "spike_detected":      spike,
            "mention_momentum":    round(momentum, 2),
            "avg_post_score":      round(avg_score, 1),
            "top_posts": [
                {k: v for k, v in p.items() if k != "created_utc"}
                for p in top_posts
            ],
            "subreddit_breakdown": {
                "wallstreetbets": breakdown.get("wallstreetbets", 0),
                "stocks":         breakdown.get("stocks", 0),
                "investing":      breakdown.get("investing", 0),
            },
        }

        # Reddit's OAuth rate limit is generous (~60-100 req/min), but a
        # small delay keeps a 24-ticker loop well clear of it.
        time.sleep(0.5)

    raise_if_too_many_failed("Reddit search (PRAW)", failed_tickers, len(universe))

    return results
