# sentiment_scorer.py
# ─────────────────────────────────────────────────────────────────────────────
# SENTIMENT SCORER — Signal Fusion and Composite Ranking Layer
#
# Responsibility: Takes the three raw signal dicts (Reddit, StockTwits,
# Fundamentals) and fuses them into one composite score per ticker.
# Ranks all tickers. Flags the top N for deep LLM analysis.
#
# Why this layer needs to exist separately:
#   Each upstream agent speaks a different "language":
#     Reddit      → mention counts, momentum floats in [-1, +1], spike booleans
#     StockTwits  → bull ratios in [0, 1], message volumes, confidence weights
#     Fundamentals→ RSI in [0, 100], volatility decimals, fundamental score [0-100]
#
#   You cannot just average these — they're on incompatible scales.
#   This layer normalises everything to [0, 1], applies weights, and
#   produces a single comparable score per ticker.
#
# Interview: "How do you fuse heterogeneous signals?"
#   → Normalise to common scale → confidence-weight each signal →
#     weighted linear combination → rank. This is the standard approach
#     in multi-factor quantitative models. More sophisticated versions
#     use PCA to decorrelate signals before combining — described as
#     a natural extension in the README.
# ─────────────────────────────────────────────────────────────────────────────

import numpy as np
import logging
from typing import Dict, List, Tuple

from config import (
    STOCK_UNIVERSE,
    SCORE_WEIGHTS,
    TOP_N_FOR_LLM,
    SPIKE_MULTIPLIER,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: INDIVIDUAL SIGNAL NORMALISERS
# Each function takes a raw signal value and returns a float in [0, 1].
# 0 = worst possible signal. 1 = best possible signal.
# ─────────────────────────────────────────────────────────────────────────────

def normalise_reddit_sentiment(mention_momentum: float, spike_detected: bool,
                                mentions_24h: int, avg_post_score: float) -> Tuple[float, float]:
    """
    Converts Reddit signals into a normalised sentiment score + confidence.

    Inputs and what they mean:
        mention_momentum: [-1, +1] — direction of mention volume change
            +1 = all recent mentions, -1 = all old mentions, 0 = stable
        spike_detected: bool — 3× above baseline in 24h
        mentions_24h: int — raw count, used to build confidence
        avg_post_score: float — community validation (upvotes)

    Scoring logic:
        Base score comes from mention_momentum mapped to [0, 1]:
            momentum of +1.0 → score of 1.0
            momentum of  0.0 → score of 0.5 (neutral)
            momentum of -1.0 → score of 0.0

        Spike bonus: if unusual activity detected, +0.15 boost
            (capped at 1.0). A spike is an additional signal ON TOP of
            momentum — it says "not only is sentiment moving, it's moving
            FASTER than normal."

        Post score modifier: high avg upvotes = community validated content.
            Normalise avg_post_score with a soft cap at 1000 upvotes.

    Confidence:
        Based on raw mention count. Low mention count = high noise.
        < 3 mentions  → 0.2 confidence (basically noise)
        3-10 mentions → 0.5 confidence (some signal)
        10-30         → 0.8 confidence
        30+           → 1.0 confidence (statistically meaningful)

    Returns:
        Tuple of (normalised_score [0,1], confidence [0,1])
    """
    # Map momentum from [-1, +1] to [0, 1]
    base_score = (mention_momentum + 1.0) / 2.0

    # Spike bonus — adds weight to anomalous activity
    spike_bonus = 0.15 if spike_detected else 0.0

    # Post score modifier — soft cap at 1000 upvotes (log scale dampens outliers)
    if avg_post_score > 0:
        # log(1001) ≈ 6.9, so scores above 1000 upvotes don't dominate
        post_modifier = min(np.log1p(avg_post_score) / np.log1p(1000), 1.0) * 0.10
    else:
        post_modifier = 0.0

    raw_score = base_score + spike_bonus + post_modifier

    # Clip to [0, 1] — bonuses can push above 1.0
    normalised = round(float(np.clip(raw_score, 0.0, 1.0)), 4)

    # Confidence based on mention volume
    if mentions_24h < 3:
        confidence = 0.2
    elif mentions_24h < 10:
        confidence = 0.5
    elif mentions_24h < 30:
        confidence = 0.8
    else:
        confidence = 1.0

    return normalised, confidence


def normalise_stocktwits_sentiment(sentiment_score: float,
                                    confidence: float,
                                    message_volume: int) -> Tuple[float, float]:
    """
    Converts StockTwits signals into normalised score + confidence.

    StockTwits sentiment_score is already in [-1, +1]:
        +1.0 = 100% bullish labeled posts
        -1.0 = 100% bearish labeled posts
         0.0 = neutral or no labeled posts

    Conversion to [0, 1]:
        (sentiment_score + 1) / 2 → same mapping as Reddit momentum

    Confidence adjustment:
        StockTwits already provides a confidence score (from stocktwits_agent.py)
        based on labeled_count. We blend it with message_volume:
        high volume + high confidence = strong signal.

    Args:
        sentiment_score: [-1, +1] from StockTwits labeled posts
        confidence:      [0, 1] from stocktwits_agent (sample size based)
        message_volume:  Raw message count (up to 30)

    Returns:
        Tuple of (normalised_score [0,1], adjusted_confidence [0,1])
    """
    # Map to [0, 1]
    normalised = round(float((sentiment_score + 1.0) / 2.0), 4)

    # Volume modifier: more messages = slightly higher confidence
    # Soft cap at 20 messages (our fetch limit is 30)
    volume_modifier = min(message_volume / 20.0, 1.0) * 0.2

    # Blend existing confidence with volume modifier
    adjusted_confidence = round(float(np.clip(confidence + volume_modifier, 0.0, 1.0)), 4)

    return normalised, adjusted_confidence


def normalise_rsi(rsi: float) -> float:
    """
    Converts RSI (0-100) into a sentiment-aligned score (0-1).

    RSI interpretation for our scoring:
        RSI 30-60 = healthy range (good entry zone) → high score
        RSI < 30  = oversold (could bounce, but also could mean trouble) → mid score
        RSI > 70  = overbought (momentum may be exhausted) → lower score
        RSI > 85  = extremely overbought → low score

    Why RSI contributes to the composite POSITIVELY in the middle range:
        We're not trying to predict short-term reversals. We're assessing
        whether the current sentiment has ROOM TO RUN. A stock at RSI 45
        with strong Reddit sentiment has more upside potential than one
        at RSI 82 with the same sentiment — the RSI 82 stock is already
        pricing in optimism.

    Interview: "Isn't a low RSI bad? Why does it score well?"
        → In isolation, low RSI can mean downtrend. But combined with
          strong positive sentiment, it means the crowd is getting excited
          about something the price hasn't reflected yet. That's the setup
          quant funds look for.

    Args:
        rsi: RSI value 0-100

    Returns:
        Normalised score [0, 1]
    """
    if rsi <= 30:
        # Oversold: potential opportunity, but could be value trap
        return 0.55
    elif rsi <= 50:
        # Neutral-to-healthy: good room to run
        return 0.75
    elif rsi <= 65:
        # Healthy momentum: best zone
        return 0.85
    elif rsi <= 75:
        # Getting extended: caution
        return 0.55
    elif rsi <= 85:
        # Overbought: momentum likely priced in
        return 0.35
    else:
        # Extremely overbought: high reversal risk
        return 0.15


def normalise_volatility(volatility: float) -> Tuple[float, str]:
    """
    Maps annualised volatility to a risk label and a score modifier.

    Note: volatility doesn't contribute to the composite score directly —
    it contributes to RISK TIER CLASSIFICATION. But we include it here
    as a modifier because high volatility amplifies both upside and downside
    of the sentiment signal.

    For the composite score:
        Low vol stocks with good sentiment → reliable signal (conservative)
        High vol stocks with good sentiment → amplified signal (speculative)

    We return a risk label here that the risk_classifier.py will use.

    Volatility brackets (annualised):
        < 20%  : Low (blue chips, utilities)
        20-35% : Moderate (most large caps)
        35-60% : High (growth stocks, TSLA-tier)
        > 60%  : Extreme (meme stocks, post-earnings moves)

    Args:
        volatility: Annualised historical volatility as decimal

    Returns:
        Tuple of (volatility_score [0,1], risk_label string)
    """
    if volatility < 0.20:
        return 0.9, "Low"
    elif volatility < 0.35:
        return 0.7, "Moderate"
    elif volatility < 0.60:
        return 0.4, "High"
    else:
        return 0.2, "Extreme"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: CONFIDENCE-WEIGHTED COMPOSITE SCORE
# ─────────────────────────────────────────────────────────────────────────────

def compute_composite_score(
    reddit_score:       float,
    reddit_confidence:  float,
    stocktwits_score:   float,
    st_confidence:      float,
    fundamental_score:  float,   # Already 0-100, needs /100
    mention_momentum:   float,   # [-1, +1], already computed
    spike_detected:     bool,
) -> float:
    """
    Combines all normalised signals into one composite score (0-100).

    Formula:
        composite = Σ (weight_i × confidence_i × signal_i) / Σ (weight_i × confidence_i)

    Why confidence-weighted and not just weight-multiplied?
        Standard weighted average: score = Σ(w_i × s_i) / Σ(w_i)
        If StockTwits has confidence=0.1 (only 1 labeled post), its weight
        should effectively be 0.1 × 0.30 = 0.03, not a full 0.30.
        Multiplying weight by confidence achieves this — low confidence
        signals self-reduce their contribution.

        This is the same concept as Bayesian updating: weak evidence
        should move your posterior less than strong evidence.

    Interview: "How is this different from a simple weighted average?"
        → The confidence term. Each signal's weight is scaled by how much
          we trust the signal at this moment. A stock with 1 StockTwits
          message has the same raw weight as one with 25 messages, but
          the confidence term reduces the effective weight proportionally.
          This prevents noise from dominating signal.

    Weights (from config.SCORE_WEIGHTS):
        sentiment_score:   0.35  (combined Reddit + StockTwits)
        mention_momentum:  0.30  (rate of change in discussion)
        fundamental_score: 0.20  (financial quality)
        unusual_activity:  0.15  (spike flag)

    Args: All normalised to [0, 1] except fundamental_score (0-100) and
          mention_momentum ([-1,+1])

    Returns:
        Composite score 0-100

    Note on the "no data at all" fallback below: fundamental_confidence is
    hardcoded to 1.0 ("fundamentals are hard data, always trust them"), and
    SCORE_WEIGHTS["fundamental_score"] is always > 0, so weight_conf_sum can
    never actually reach 0 through this function's normal call path — the
    fallback is effectively unreachable as long as a fundamental_score is
    supplied. This is intentional, not a latent bug: when reddit/StockTwits
    confidence are both 0 (no social data at all), the composite
    deliberately collapses to exactly the fundamental score rather than a
    flat 50.0 — trusting the one signal we do have (yfinance fundamentals)
    over an artificial neutral guess. Confirmed and left as-is; see BUGS.md.
    """
    w = SCORE_WEIGHTS

    # ── SENTIMENT COMPONENT ──────────────────────────────────────────────────
    # Blend Reddit and StockTwits into single sentiment score
    # Weight each by its own confidence, then average
    total_sent_conf = reddit_confidence + st_confidence
    if total_sent_conf > 0:
        blended_sentiment = (
            (reddit_score * reddit_confidence) +
            (stocktwits_score * st_confidence)
        ) / total_sent_conf
        sentiment_confidence = min(total_sent_conf / 2.0, 1.0)
    else:
        blended_sentiment    = 0.5   # No data → neutral
        sentiment_confidence = 0.0

    # ── MOMENTUM COMPONENT ───────────────────────────────────────────────────
    # mention_momentum is [-1, +1], map to [0, 1]
    momentum_normalised   = (mention_momentum + 1.0) / 2.0
    # Confidence for momentum: we always have it if we have Reddit data
    momentum_confidence   = reddit_confidence

    # ── FUNDAMENTAL COMPONENT ────────────────────────────────────────────────
    # fundamental_score is 0-100, scale to 0-1
    fundamental_normalised   = fundamental_score / 100.0
    fundamental_confidence   = 1.0   # Fundamentals are hard data, always trust them

    # ── UNUSUAL ACTIVITY COMPONENT ───────────────────────────────────────────
    # Boolean spike → binary signal
    spike_normalised   = 1.0 if spike_detected else 0.0
    spike_confidence   = reddit_confidence   # Only meaningful if we have Reddit data

    # ── CONFIDENCE-WEIGHTED COMPOSITE ───────────────────────────────────────
    # Numerator: each signal × its weight × its confidence
    # Denominator: sum of (weight × confidence) for normalisation

    components = [
        (w["sentiment_score"],   sentiment_confidence,    blended_sentiment),
        (w["mention_momentum"],  momentum_confidence,     momentum_normalised),
        (w["fundamental_score"], fundamental_confidence,  fundamental_normalised),
        (w["unusual_activity"],  spike_confidence,        spike_normalised),
    ]

    weighted_sum    = sum(weight * conf * signal for weight, conf, signal in components)
    weight_conf_sum = sum(weight * conf          for weight, conf, _      in components)

    if weight_conf_sum == 0:
        return 50.0   # No data at all → neutral score

    # Scale to 0-100
    composite = (weighted_sum / weight_conf_sum) * 100
    return round(float(np.clip(composite, 0.0, 100.0)), 2)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: MASTER SCORING FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def score_all_tickers(
    reddit_data:       Dict[str, dict],
    stocktwits_data:   Dict[str, dict],
    fundamentals_data: Dict[str, dict],
    universe:          List[str] = STOCK_UNIVERSE,
) -> List[dict]:
    """
    Scores every ticker in the universe and returns a ranked list.

    This is the function LangGraph's orchestration node will call.
    It receives the three raw agent outputs and returns one clean,
    ranked, enriched list ready for LLM and the risk classifier.

    Output schema per ticker:
    {
        "ticker":               "NVDA",
        "composite_score":      78.4,        # 0-100, higher = better signal
        "rank":                 1,           # 1 = highest composite score
        "send_to_llm":       True,        # Top 10 get full LLM analysis
        "blended_sentiment":    0.82,        # [0,1] combined Reddit+ST sentiment
        "sentiment_confidence": 0.85,        # How much to trust the sentiment
        "mention_momentum":     0.61,        # [-1,+1] Reddit mention direction
        "spike_detected":       True,        # Unusual activity flag
        "mentions_24h":         34,
        "st_bull_ratio":        0.74,        # StockTwits % bullish
        "fundamental_score":    72.0,        # 0-100 financial quality
        "rsi":                  58.3,
        "volatility":           0.42,
        "volatility_label":     "High",
        "momentum_30d":         0.18,        # +18% over 30 days
        "current_price":        487.23,
        "daily_change_pct":     2.14,
        "sector":               "Technology",
        "top_reddit_posts":     [...],       # For LLM
        "top_st_messages":      [...],       # For LLM
        "price_chart":          [...],       # 30d closes, for frontend charting
    }

    Interview: "What does the output of your scoring layer look like?"
        → This schema. Fully enriched, self-contained per ticker.
          Every downstream component (LLM, risk classifier, UI) reads
          from this and needs nothing else.

    Args:
        reddit_data:       Output of fetch_reddit_sentiment()
        stocktwits_data:   Output of fetch_all_stocktwits()
        fundamentals_data: Output of fetch_all_fundamentals()
        universe:          Ticker list to score

    Returns:
        List of scored ticker dicts, sorted by composite_score descending
    """
    scored = []

    for ticker in universe:
        # ── GET RAW DATA FOR THIS TICKER ────────────────────────────────────
        rd = reddit_data.get(ticker, {})
        st = stocktwits_data.get(ticker, {})
        fn = fundamentals_data.get(ticker, {})

        # Skip tickers where we have no data at all
        # (yfinance failure — uncommon but possible for delisted stocks)
        if not fn:
            logger.warning(f"No fundamental data for {ticker} — skipping")
            continue

        # ── NORMALISE INDIVIDUAL SIGNALS ─────────────────────────────────────
        reddit_score, reddit_conf = normalise_reddit_sentiment(
            mention_momentum = rd.get("mention_momentum", 0.0),
            spike_detected   = rd.get("spike_detected", False),
            mentions_24h     = rd.get("mentions_24h", 0),
            avg_post_score   = rd.get("avg_post_score", 0.0),
        )

        st_score, st_conf = normalise_stocktwits_sentiment(
            sentiment_score = st.get("sentiment_score", 0.0),
            confidence      = st.get("confidence", 0.0),
            message_volume  = st.get("message_volume", 0),
        )

        rsi_score              = normalise_rsi(fn.get("rsi", 50.0))
        vol_score, vol_label   = normalise_volatility(fn.get("volatility", 0.30))

        # ── BLENDED SENTIMENT (for output schema) ────────────────────────────
        total_conf = reddit_conf + st_conf
        if total_conf > 0:
            blended = (reddit_score * reddit_conf + st_score * st_conf) / total_conf
        else:
            blended = 0.5

        # ── COMPOSITE SCORE ──────────────────────────────────────────────────
        composite = compute_composite_score(
            reddit_score      = reddit_score,
            reddit_confidence = reddit_conf,
            stocktwits_score  = st_score,
            st_confidence     = st_conf,
            fundamental_score = fn.get("fundamental_score", 50.0),
            mention_momentum  = rd.get("mention_momentum", 0.0),
            spike_detected    = rd.get("spike_detected", False),
        )

        # ── BUILD ENRICHED OUTPUT DICT ───────────────────────────────────────
        scored.append({
            # Core scores
            "ticker":               ticker,
            "composite_score":      composite,
            "blended_sentiment":    round(blended, 4),
            "sentiment_confidence": round(min(total_conf / 2.0, 1.0), 4),
            "rsi_score":            rsi_score,
            "volatility_score":     vol_score,

            # Reddit signals
            "mention_momentum":     rd.get("mention_momentum", 0.0),
            "spike_detected":       rd.get("spike_detected", False),
            "mentions_24h":         rd.get("mentions_24h", 0),
            "mentions_7d":          rd.get("mentions_7d", 0),
            "avg_post_score":       rd.get("avg_post_score", 0.0),
            "subreddit_breakdown":  rd.get("subreddit_breakdown", {}),
            "top_reddit_posts":     rd.get("top_posts", []),

            # StockTwits signals
            "st_bull_ratio":        st.get("bull_ratio", 0.5),
            "st_sentiment_score":   st.get("sentiment_score", 0.0),
            "st_message_volume":    st.get("message_volume", 0),
            "st_confidence":        st.get("confidence", 0.0),
            "top_st_messages":      st.get("top_messages", []),

            # Fundamentals
            "fundamental_score":    fn.get("fundamental_score", 50.0),
            "rsi":                  fn.get("rsi", 50.0),
            "volatility":           fn.get("volatility", 0.30),
            "volatility_label":     vol_label,
            "momentum_30d":         fn.get("momentum_30d", 0.0),
            "volume_ratio":         fn.get("volume_ratio", 1.0),
            "current_price":        fn.get("current_price", 0.0),
            "daily_change_pct":     fn.get("daily_change_pct", 0.0),
            "market_cap":           fn.get("market_cap", 0),
            "pe_ratio":             fn.get("pe_ratio"),
            "sector":               fn.get("sector", "Unknown"),
            "price_chart":          fn.get("price_chart", []),
        })

    # ── RANK BY COMPOSITE SCORE ──────────────────────────────────────────────
    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    # ── FLAG TOP N FOR LLM ────────────────────────────────────────────────
    # Only top TOP_N_FOR_LLM (=10) get full LLM synthesis.
    # The rest get rule-based risk classification only.
    # This controls both API cost and latency.
    for i, entry in enumerate(scored):
        entry["rank"]          = i + 1
        entry["send_to_llm"] = (i < TOP_N_FOR_LLM)

    # Log summary
    top5 = [(e["ticker"], e["composite_score"]) for e in scored[:5]]
    spikes = [e["ticker"] for e in scored if e["spike_detected"]]
    logger.info(f"Scoring complete. Top 5: {top5} | Spikes: {spikes}")

    return scored


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: TRENDING NOW SPOTLIGHT
# ─────────────────────────────────────────────────────────────────────────────

def get_trending_now(scored_tickers: List[dict], n: int = 3) -> List[dict]:
    """
    Returns the N stocks with the highest mention velocity spike in 24h.
    These appear in the "Trending Now" spotlight above the main ranked list.

    Why a separate trending spotlight?
        The composite score rewards stocks that score well on ALL dimensions.
        A stock can spike on Reddit but have weak fundamentals and score
        moderately overall. The trending spotlight specifically surfaces
        "what's being talked about RIGHT NOW" regardless of quality.

        Interview: "What's the difference between your ranked list and trending?"
        → Ranked list = composite quality + sentiment signal (WHERE to look)
          Trending Now = pure mention velocity (WHAT people are talking about)
          They answer different questions. A trader wants both.

    Selection: From spike-detected tickers, pick top 3 by mentions_24h.
    If fewer than 3 spikes, fill with highest mention_momentum tickers.

    Args:
        scored_tickers: Full ranked list from score_all_tickers()
        n:              How many trending stocks to surface (default 3)

    Returns:
        List of n ticker dicts, ordered by mention activity
    """
    # First: any spike-detected tickers, sorted by 24h mentions
    spiked = [t for t in scored_tickers if t["spike_detected"]]
    spiked.sort(key=lambda x: x["mentions_24h"], reverse=True)

    trending = spiked[:n]

    # Backfill with highest momentum if we don't have enough spikes
    if len(trending) < n:
        non_spiked = [t for t in scored_tickers if not t["spike_detected"]]
        non_spiked.sort(key=lambda x: x["mention_momentum"], reverse=True)
        needed = n - len(trending)
        trending.extend(non_spiked[:needed])

    return trending[:n]