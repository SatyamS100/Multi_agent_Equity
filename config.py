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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Groq model id used for synthesis + evaluation (see graph.py). Kept
# env-overridable rather than hardcoded in graph.py: Groq has deprecated a
# model this project depended on before (see CONTEXT.md) — when that
# happens again, swapping GROQ_MODEL in .env is a config change, not a
# code change. Current default: https://console.groq.com/docs/models
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# ── CORS ───────────────────────────────────────────────────────────────────────
# Comma-separated list of origins allowed to call the backend API.
# Falls back to common local-dev frontend origins if unset.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if origin.strip()
]

# ── STOCK UNIVERSE ────────────────────────────────────────────────────────────
# 24 tickers chosen deliberately across risk tiers:
#   Mega-cap Tech:            AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AMD
#   High Beta / Retail:       PLTR, COIN, SHOP, SQ, GME, AMC, MSTR
#   Value / Dividend:         JPM, XOM, PFE, DIS
#   Speculative / Growth:     SOFI, RIVN, RBLX, SNAP, HOOD
#
# Interview: "How would you scale to S&P 500?"
#   → Batch LLM calls (top-N by activity, not all 500)
#   → Add Redis cache so unchanged tickers don't re-fetch

STOCK_UNIVERSE = [
    # Mega-cap Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    # High Beta / Retail Darlings
    "PLTR", "COIN", "SHOP", "SQ", "GME", "AMC", "MSTR",
    # Value / Dividend
    "JPM", "XOM", "PFE", "DIS",
    # Speculative / Growth
    "SOFI", "RIVN", "RBLX", "SNAP", "HOOD"
]

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
# These buckets let the frontend's risk slider filter meaningfully.
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