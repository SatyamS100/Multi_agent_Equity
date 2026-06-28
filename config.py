# config.py
# ─────────────────────────────────────────────────────────────────────────────
# Central configuration file. Every constant, threshold, and universe
# definition lives here. This is intentional — if anything changes (bigger
# universe, different subreddits, tuned thresholds), you change ONE file.
# ─────────────────────────────────────────────────────────────────────────────

from dotenv import load_dotenv
import os

load_dotenv()  # Pulls variables from .env into os.environ

# ── API CREDENTIALS ───────────────────────────────────────────────────────────
# Loaded from .env — never hardcode keys in source files.
# Interview note: In production this would use a secrets manager (AWS Secrets
# Manager, HashiCorp Vault). .env is appropriate for dev/demo.

REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "SentimentBot/1.0")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")

# ── STOCK UNIVERSE ────────────────────────────────────────────────────────────
# 25 tickers chosen deliberately across risk tiers:
#   Mega-cap stable:   AAPL, MSFT, GOOGL, AMZN, NVDA, META
#   High-beta growth:  TSLA, AMD, PLTR, COIN, SHOP, SQ
#   Meme-adjacent:     GME, AMC, BBBY (these generate WSB noise)
#   Sectoral mix:      JPM (finance), XOM (energy), PFE (pharma), DIS (media)
#   Mid-cap volatile:  SOFI, RIVN, LCID, RBLX, SNAP, HOOD
#
# Interview: "How would you scale to S&P 500?"
#   → Parallelise reddit_agent using asyncpraw (async version of PRAW)
#   → Batch LLM calls (top-N by activity, not all 500)
#   → Add Redis cache so unchanged tickers don't re-fetch

STOCK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",   # Mega-cap
    "TSLA", "AMD",  "PLTR", "COIN",  "SHOP", "SQ",      # High-beta growth
    "GME",  "AMC",                                        # Meme stocks
    "JPM",  "XOM",  "PFE",  "DIS",                       # Sectoral
    "SOFI", "RIVN", "RBLX", "SNAP", "HOOD"               # Mid-cap volatile
]

# ── REDDIT CONFIGURATION ──────────────────────────────────────────────────────
# Three subreddits chosen because they represent three distinct investor
# archetypes with very different signal characteristics:
#
#   r/wallstreetbets → Retail speculators, high emotion, meme-driven, 
#                      sarcasm-heavy. Noisy but leads price action on 
#                      meme stocks. WSB coined "YOLO" and "tendies."
#
#   r/stocks         → More analytical retail investors. Discussions include
#                      earnings analysis, sector rotations, macro. 
#                      Less noise than WSB.
#
#   r/investing      → Long-term, fundamentals-oriented. Lower frequency but
#                      higher signal-to-noise. Good counter-signal to WSB.

SUBREDDITS = ["wallstreetbets", "stocks", "investing"]

# How many posts to pull per subreddit per ticker per scrape cycle
POSTS_PER_SUBREDDIT = 50

# ── SPIKE DETECTION THRESHOLD ─────────────────────────────────────────────────
# If a ticker's 24h mention count is ≥ SPIKE_MULTIPLIER × its 7-day daily
# average, it's flagged as "unusual activity."
# 
# Why 3×? Empirically, 2× generates too many false positives (normal variance),
# 5× misses early-stage spikes. 3× is the standard in alternative data shops.
# Interview: "How did you choose 3×?" → You can say it's tunable and you'd
# validate it against your backtesting layer in Phase 2.

SPIKE_MULTIPLIER = 3.0

# ── LLM SYNTHESIS: HOW MANY STOCKS GET DEEP ANALYSIS ─────────────────────
# Full LLM synthesis (reading actual post text, generating bull/bear case)
# is expensive in tokens and latency. Solution: rank all stocks by raw
# social activity score first, run full LLM on top N, rule-based scoring
# on the rest.
#
# Interview: "How do you control API costs at scale?"
# → This tiered approach. Top 10 get LLM synthesis, rest get heuristic scoring.
# → In production, cache LLM outputs for 6 hours (sentiment doesn't change
#   minute-to-minute).

TOP_N_FOR_LLM = 10

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
# Final risk-reward score is a weighted combination of four signals.
# These weights are hyperparameters — in a real fund you'd optimise them
# against a validation set of historical spike→return pairs.
#
# Current weights reflect the thesis that sentiment momentum is the strongest
# short-term predictor, fundamentals prevent false positives on garbage stocks.

SCORE_WEIGHTS = {
    "sentiment_score":   0.35,   # LLM-assessed sentiment quality (-1 to +1)
    "mention_momentum":  0.30,   # Rate of change in mention volume (7-day)
    "fundamental_score": 0.20,   # Quantitative financial health score
    "unusual_activity":  0.15,   # Binary spike flag, weighted into composite
}

# ── RISK TIER THRESHOLDS ──────────────────────────────────────────────────────
# Composite score (0–100) maps to investor risk profile.
# These buckets let the Streamlit slider filter meaningfully.
#
# Conservative:  Strong fundamentals, low volatility, moderate positive sentiment
# Moderate:      Decent fundamentals, some momentum, acceptable risk
# Aggressive:    Weaker fundamentals compensated by strong momentum signal
# Speculative:   Low scores or extreme volatility — high risk, high reward

RISK_TIERS = {
    "Conservative": (65, 100),
    "Moderate":     (45, 65),
    "Aggressive":   (30, 45),
    "Speculative":  (0,  30),
}

# ── TECHNICAL INDICATOR PARAMETERS ───────────────────────────────────────────
RSI_PERIOD        = 14   # Standard 14-day RSI (Wilder's original)
MOMENTUM_WINDOW   = 30   # 30-day price momentum lookback
VOLATILITY_WINDOW = 30   # 30-day rolling volatility (annualised)