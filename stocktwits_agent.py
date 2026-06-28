# src/stocktwits_agent.py
# ─────────────────────────────────────────────────────────────────────────────
# STOCKTWITS AGENT — Labeled Financial Sentiment Layer
#
# Responsibility: For every ticker, hit StockTwits' public API and return
# bullish/bearish ratios, message volume, and recent message text.
#
# Why StockTwits specifically?
#   1. FREE public API — no authentication required for basic endpoints
#   2. FINANCE-SPECIFIC — every user is discussing stocks, not cat videos
#   3. SELF-LABELED SENTIMENT — users manually tag posts Bullish/Bearish
#      This is ground-truth labeled data. No NLP inference needed.
#      Reddit gives you text you have to interpret. StockTwits gives you
#      the interpretation directly from the author.
#   4. VOLUME METRICS — the API returns message count over 24h, which
#      is an independent confirmation signal for Reddit spike detection
#
# Why not Twitter/X?
#   $100/month minimum for API access since Elon's 2023 changes.
#   StockTwits is free, more relevant, and actually better for stocks.
#   Never pay for data you can get free at the same or better quality.
#
# Interview: "What makes StockTwits signal different from Reddit signal?"
#   → Reddit = organic community discussion, often long-form, sarcasm-heavy,
#     requires NLP interpretation. Signal character: noisy but early-moving.
#   → StockTwits = short-form, finance-only, USER-LABELED sentiment.
#     Signal character: cleaner, lower noise, but less granular context.
#   → Together: Reddit catches narrative shifts early, StockTwits confirms
#     with labeled signal. Correlated spikes = high conviction.
# ─────────────────────────────────────────────────────────────────────────────

import requests
import time
import logging
from typing import Dict, List, Optional

from config import STOCK_UNIVERSE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── API CONSTANTS ─────────────────────────────────────────────────────────────
# StockTwits public API base URL. No API key needed for these endpoints.
# Rate limit: ~200 requests/hour on the public tier (unauthenticated).
# Interview: "How do you handle rate limits?"
#   → TIME_BETWEEN_CALLS enforces a polite inter-request delay.
#   → Exponential backoff on 429 responses (see fetch_stocktwits_data).

STOCKTWITS_BASE_URL   = "https://api.stocktwits.com/api/2"
TIME_BETWEEN_CALLS    = 0.5   # 500ms between calls → max 120 req/min, well under limit
MAX_RETRIES           = 3     # Retry failed requests this many times
MESSAGES_TO_FETCH     = 30    # Most recent messages per ticker


# ── SINGLE TICKER FETCH ───────────────────────────────────────────────────────
def fetch_stocktwits_data(ticker: str) -> Optional[dict]:
    """
    Fetches StockTwits stream for a single ticker with retry logic.

    Endpoint used:
        GET /streams/symbol/{ticker}.json
        Returns the 30 most recent messages for that ticker symbol,
        including user sentiment labels and message metadata.

    Why retry logic?
        Network calls fail. Rate limits hit. StockTwits occasionally returns
        500s. Without retries, one bad response kills the whole ticker.
        Exponential backoff (wait longer each retry) is standard practice.

        Interview: "How do you make your data pipeline resilient?"
        → Retry with backoff, never crash on single failure, log everything.

    Args:
        ticker: Stock symbol, e.g. "TSLA"

    Returns:
        Raw API response dict, or None if all retries failed
    """
    url = f"{STOCKTWITS_BASE_URL}/streams/symbol/{ticker}.json"
    params = {"limit": MESSAGES_TO_FETCH}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=10,   # 10 second timeout — don't hang forever
            )

            if response.status_code == 200:
                return response.json()

            elif response.status_code == 429:
                # Rate limited — wait longer before retry
                # Exponential backoff: wait 2^attempt seconds (2, 4, 8)
                wait_time = (2 ** attempt) * 2
                logger.warning(
                    f"Rate limited on {ticker}. "
                    f"Waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}"
                )
                time.sleep(wait_time)

            elif response.status_code == 404:
                # Ticker not found on StockTwits — not an error, just no data
                logger.debug(f"{ticker} not found on StockTwits")
                return None

            else:
                logger.warning(
                    f"Unexpected status {response.status_code} for {ticker} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching {ticker} (attempt {attempt + 1})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {ticker} (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"Unexpected error fetching {ticker}: {e}")
            return None  # Unknown error — don't retry

    logger.error(f"All {MAX_RETRIES} attempts failed for {ticker}")
    return None


# ── PARSE RAW API RESPONSE ────────────────────────────────────────────────────
def parse_stocktwits_response(ticker: str, raw_data: dict) -> dict:
    """
    Extracts signal-relevant fields from raw StockTwits API response.

    Raw StockTwits response structure (simplified):
    {
        "symbol": {"symbol": "TSLA", "watchlist_count": 184932},
        "messages": [
            {
                "id": 123456,
                "body": "TSLA breaking out! Massive volume today",
                "created_at": "2024-01-15T14:23:00Z",
                "entities": {
                    "sentiment": {"basic": "Bullish"}   ← THE GOLD
                },
                "likes": {"total": 12},
                "reshares": {"reshared_count": 3}
            },
            ...
        ]
    }

    The "sentiment" field is what makes StockTwits uniquely valuable.
    Users explicitly choose Bullish/Bearish when posting.
    We compute the RATIO of bullish to total labeled posts.

    Why ratio and not raw count?
        30 bullish and 10 bearish = 75% bull ratio
        3 bullish and 1 bearish  = 75% bull ratio
        Same ratio, very different volume. We capture BOTH:
        - bull_ratio tells us directional lean
        - message_volume tells us how much signal exists
        Low volume → low confidence in the ratio. High volume → high confidence.

    Interview: "How do you handle unlabeled posts?"
        → We compute ratio only over LABELED posts (those with a sentiment tag).
          Unlabeled posts still contribute to volume/text but not to ratio.
          This prevents dilution of the directional signal.

    Args:
        ticker:   Stock symbol (for output labeling)
        raw_data: Full API response dict from StockTwits

    Returns:
        Structured dict with parsed signals
    """
    messages = raw_data.get("messages", [])
    symbol_data = raw_data.get("symbol", {})

    # ── COUNT LABELED SENTIMENT ──────────────────────────────────────────────
    bullish_count  = 0
    bearish_count  = 0
    unlabeled      = 0
    message_texts  = []   # Top messages for LLM to read

    for msg in messages:
        body = msg.get("body", "")
        if body:
            message_texts.append({
                "text":       body,
                "created_at": msg.get("created_at", ""),
                "likes":      msg.get("likes", {}).get("total", 0),
            })

        # Dig into the entities object to find the sentiment label
        # Path: entities → sentiment → basic → "Bullish" or "Bearish"
        sentiment_obj = msg.get("entities", {}).get("sentiment", None)

        if sentiment_obj is None:
            unlabeled += 1   # User didn't tag their sentiment — happens ~40% of posts
            continue

        label = sentiment_obj.get("basic", "").lower()
        if label == "bullish":
            bullish_count += 1
        elif label == "bearish":
            bearish_count += 1
        else:
            unlabeled += 1

    # ── COMPUTE BULL RATIO ───────────────────────────────────────────────────
    # Only over labeled posts. Unlabeled posts don't affect direction.
    labeled_total = bullish_count + bearish_count

    if labeled_total > 0:
        bull_ratio = round(bullish_count / labeled_total, 4)
        # Convert to [-1, +1] scale to match Reddit sentiment scale
        # bull_ratio of 1.0 (all bullish) → sentiment_score of +1.0
        # bull_ratio of 0.0 (all bearish) → sentiment_score of -1.0
        # bull_ratio of 0.5 (neutral)     → sentiment_score of  0.0
        sentiment_score = round((bull_ratio * 2) - 1, 4)
    else:
        bull_ratio      = 0.5    # No labeled data → assume neutral
        sentiment_score = 0.0

    # ── WATCHLIST COUNT ──────────────────────────────────────────────────────
    # How many StockTwits users have this stock on their watchlist.
    # This is a slow-moving baseline signal — TSLA has 180K+ watchers,
    # a micro-cap might have 200. Not a momentum signal, but useful for
    # contextualising the message volume.
    watchlist_count = symbol_data.get("watchlist_count", 0)

    # ── ENGAGEMENT SCORE ─────────────────────────────────────────────────────
    # Weight messages by likes (community validation, same principle as
    # Reddit upvotes). High likes = message resonated with community.
    total_likes = sum(m.get("likes", 0) for m in message_texts)
    avg_likes   = round(total_likes / len(message_texts), 2) if message_texts else 0.0

    # Sort by likes for LLM — show it the messages the community found most compelling
    top_messages = sorted(message_texts, key=lambda m: m["likes"], reverse=True)[:5]

    return {
        "ticker":           ticker,
        "message_volume":   len(messages),          # Total messages fetched (up to 30)
        "labeled_count":    labeled_total,           # How many had a sentiment label
        "bullish_count":    bullish_count,
        "bearish_count":    bearish_count,
        "unlabeled_count":  unlabeled,
        "bull_ratio":       bull_ratio,              # 0.0 (all bear) to 1.0 (all bull)
        "sentiment_score":  sentiment_score,         # -1.0 to +1.0, matches Reddit scale
        "watchlist_count":  watchlist_count,
        "avg_likes":        avg_likes,               # Community validation signal
        "top_messages":     top_messages,            # For LLM to read
        "confidence":       _compute_confidence(labeled_total),
    }


# ── CONFIDENCE WEIGHTING ──────────────────────────────────────────────────────
def _compute_confidence(labeled_count: int) -> float:
    """
    Returns a confidence weight (0.0 to 1.0) based on how many labeled
    posts exist. Low sample size → low confidence → downstream agents
    should weight this signal less.

    Why this matters (interview):
        A 90% bull ratio from 2 labeled posts is meaningless.
        A 90% bull ratio from 25 labeled posts is a strong signal.
        Statistical significance scales with sample size.
        This function encodes that intuition simply.

        In a production system you'd use a proper Bayesian prior or
        Wilson score interval. For our purposes, a linear ramp to a
        cap is sufficient and explainable.

    Scale:
        0  labeled posts → 0.0 confidence
        5  labeled posts → 0.33 confidence
        10 labeled posts → 0.67 confidence
        15+ labeled posts → 1.0 confidence (full confidence)
    """
    if labeled_count <= 0:
        return 0.0
    return round(min(labeled_count / 15.0, 1.0), 4)


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────────
def fetch_all_stocktwits(universe: List[str] = STOCK_UNIVERSE) -> Dict[str, dict]:
    """
    Fetches and parses StockTwits data for every ticker in the universe.

    Why sequential and not parallel?
        StockTwits public tier rate limit is ~200 req/hour.
        With 25 tickers and 0.5s delay = 12.5 seconds total. Fast enough.
        Parallelising would risk hitting rate limits and complicating error
        handling. Not worth it at this scale.

        Interview: "When would you parallelise this?"
        → At 500+ tickers. Use asyncio + aiohttp, semaphore-bounded to
          stay under rate limits. Same logic, async execution model.

    Returns:
        Dict mapping ticker → parsed StockTwits signal dict.
        Every ticker in universe is present (empty signal if no data).
    """
    results = {}

    for i, ticker in enumerate(universe):
        logger.info(f"Fetching StockTwits [{i+1}/{len(universe)}]: {ticker}")

        raw = fetch_stocktwits_data(ticker)

        if raw is None:
            # No data available — return zeroed-out signal for this ticker
            # Downstream agents always get a complete universe
            results[ticker] = {
                "ticker":          ticker,
                "message_volume":  0,
                "labeled_count":   0,
                "bullish_count":   0,
                "bearish_count":   0,
                "unlabeled_count": 0,
                "bull_ratio":      0.5,
                "sentiment_score": 0.0,
                "watchlist_count": 0,
                "avg_likes":       0.0,
                "top_messages":    [],
                "confidence":      0.0,
            }
        else:
            results[ticker] = parse_stocktwits_response(ticker, raw)

        # Polite delay between calls — don't hammer the API
        time.sleep(TIME_BETWEEN_CALLS)

    # Summary
    bullish_tickers = [
        t for t, d in results.items() if d["sentiment_score"] > 0.3
    ]
    bearish_tickers = [
        t for t, d in results.items() if d["sentiment_score"] < -0.3
    ]

    logger.info(
        f"StockTwits complete. "
        f"Bullish: {bullish_tickers} | Bearish: {bearish_tickers}"
    )

    return results