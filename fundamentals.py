# fundamentals.py
# ─────────────────────────────────────────────────────────────────────────────
# FUNDAMENTALS AGENT — Quantitative Financial Signal Layer
#
# Responsibility: For every ticker, pull price history and financial ratios,
# compute technical indicators, and return a quantitative fingerprint that
# grounds the social sentiment signal in financial reality.
#
# Why this layer exists:
#   Reddit can make any stock trend. GME, AMC, BBBY — all had euphoric
#   sentiment before collapsing. Sentiment without fundamentals is noise.
#   This layer provides the quantitative context that separates a legitimate
#   breakout from a pump-and-dump.
#
# Connection to Options Pricer (interview bridge):
#   The 30-day historical volatility computed here uses the EXACT same
#   log-return standard deviation method as your Black-Scholes σ input.
#   Same formula, different application. Shows consistent quant thinking.
#
# Data source: yfinance
#   Free, no API key, wraps Yahoo Finance. Used by quant researchers,
#   academic papers, and hedge fund interns worldwide. Limitations:
#   15-min delayed prices (fine for daily sentiment cycles), occasional
#   missing data for small caps (handled with fallbacks below).
# ─────────────────────────────────────────────────────────────────────────────

import yfinance as yf
import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional

from config import (
    STOCK_UNIVERSE,
    RSI_PERIOD,
    MOMENTUM_WINDOW,
    VOLATILITY_WINDOW,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── RSI CALCULATION ───────────────────────────────────────────────────────────
def compute_rsi(prices: pd.Series, period: int = RSI_PERIOD) -> float:
    """
    Computes the Relative Strength Index (RSI) for a price series.

    What RSI measures:
        RSI quantifies the SPEED and MAGNITUDE of recent price movements.
        It oscillates between 0 and 100.
        > 70 = overbought (price moved up too fast, potential reversal)
        < 30 = oversold  (price moved down too fast, potential bounce)
        40-60 = neutral

    Why RSI matters for this project:
        Sentiment + RSI together are powerful. High Reddit sentiment +
        RSI already at 80 = late to the party, risk of reversal.
        High Reddit sentiment + RSI at 45 = early signal, room to run.
        RSI contextualises WHETHER the sentiment signal is still actionable.

    Wilder's RSI formula:
        1. Compute daily price changes (deltas)
        2. Separate into gains (positive deltas) and losses (negative deltas)
        3. Compute average gain and average loss over RSI_PERIOD (14) days
        4. RS = avg_gain / avg_loss
        5. RSI = 100 - (100 / (1 + RS))

    Interview: "Why 14 periods?"
        → J. Welles Wilder (inventor of RSI) chose 14 in 1978 and it became
          the industry standard. It balances sensitivity vs noise. 7-period
          RSI is too noisy, 21-period is too slow. 14 is convention.

    Args:
        prices: Pandas Series of closing prices, chronological order
        period: Lookback window (default 14, from config)

    Returns:
        RSI value as float (0-100), or 50.0 if insufficient data
    """
    if len(prices) < period + 1:
        return 50.0   # Insufficient data → neutral RSI, don't penalise

    # Daily price changes
    delta = prices.diff().dropna()

    # Separate gains and losses
    # clip(lower=0) zeroes out negatives (keeps only gains)
    # clip(upper=0) zeroes out positives then abs (keeps only losses)
    gains  = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)   # Make losses positive

    # Wilder's smoothed moving average (not simple average)
    # ewm(com=period-1) implements Wilder's smoothing:
    #   α = 1/period, so com = (1/α) - 1 = period - 1
    # Why EWM not SMA? Recent price changes should matter more than old ones.
    avg_gain = gains.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
    avg_loss = losses.ewm(com=period - 1, min_periods=period).mean().iloc[-1]

    if avg_loss == 0:
        return 100.0   # No losses at all → maximum RSI

    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 2)


# ── HISTORICAL VOLATILITY ─────────────────────────────────────────────────────
def compute_historical_volatility(prices: pd.Series, window: int = VOLATILITY_WINDOW) -> float:
    """
    Computes annualised historical volatility from log returns.

    THIS IS THE SAME FORMULA AS YOUR OPTIONS PRICER.

    In Black-Scholes, σ (sigma) = annualised volatility of the underlying.
    You computed it as: std(log returns) × sqrt(252).
    That's exactly what this function does.

    Why log returns instead of simple returns?
        Simple return: (P_t - P_{t-1}) / P_{t-1}
        Log return:    ln(P_t / P_{t-1})

        Log returns are:
        1. Time-additive (you can sum daily log returns to get period return)
        2. Normally distributed (better for statistical assumptions)
        3. Symmetric (a 50% gain then 50% loss = back to start with log returns)
        Simple returns are none of these. Log returns are the standard in quant.

    Annualisation:
        Daily vol × sqrt(252) = Annual vol
        252 = trading days per year (not 365 — markets are closed weekends/holidays)

    Risk stratification use:
        Low vol  (< 25%):  Conservative tier candidate
        Med vol (25-50%):  Moderate/Aggressive
        High vol (> 50%):  Speculative (meme stocks, crypto-adjacent)

    Interview: "What's the volatility of TSLA typically?"
        → ~60-80% annualised. For reference, SPY (S&P 500 ETF) is ~15-20%.
          GME during the squeeze hit ~500%+.

    Args:
        prices: Pandas Series of closing prices
        window: Rolling window in trading days (default 30)

    Returns:
        Annualised volatility as decimal (e.g. 0.45 = 45%), or 0.3 if insufficient data
    """
    if len(prices) < window + 1:
        return 0.30   # Fallback: assume 30% vol (mid-range default)

    # Log returns: ln(today's price / yesterday's price)
    log_returns = np.log(prices / prices.shift(1)).dropna()

    # Take the most recent `window` days
    recent_returns = log_returns.tail(window)

    # Daily standard deviation of log returns
    daily_vol = recent_returns.std()

    # Annualise: multiply by sqrt(trading days per year)
    annual_vol = daily_vol * np.sqrt(252)

    return round(float(annual_vol), 4)


# ── PRICE MOMENTUM ────────────────────────────────────────────────────────────
def compute_momentum(prices: pd.Series, window: int = MOMENTUM_WINDOW) -> float:
    """
    Computes price momentum as percentage return over the lookback window.

    What momentum measures:
        Simple question: "Is this stock going up or down over the past month?"
        Momentum = (current price / price 30 days ago) - 1
        Positive = uptrend. Negative = downtrend.

    Why momentum matters alongside sentiment:
        Sentiment predicts SHORT-term moves (days).
        Momentum shows what's ALREADY happened (last 30 days).
        Together: is sentiment building on existing momentum (continuation)
        or contrarian (reversal setup)?

        High positive sentiment + negative momentum = potential reversal signal
        High positive sentiment + positive momentum = momentum continuation

    Interview: "What's the difference between RSI and momentum?"
        → RSI is RELATIVE (compares recent gains to recent losses, scaled 0-100).
          Momentum is ABSOLUTE (raw % return over a period).
          RSI tells you if a move is getting overextended.
          Momentum tells you the direction and magnitude of the trend.

    Args:
        prices: Pandas Series of closing prices
        window: Lookback period in trading days

    Returns:
        Momentum as decimal (e.g. 0.15 = +15% over 30 days), or 0.0 if insufficient
    """
    if len(prices) < window + 1:
        return 0.0

    price_now  = prices.iloc[-1]
    price_then = prices.iloc[-(window + 1)]

    if price_then == 0:
        return 0.0

    momentum = (price_now - price_then) / price_then
    return round(float(momentum), 4)


# ── FUNDAMENTAL SCORE ─────────────────────────────────────────────────────────
def compute_fundamental_score(info: dict) -> float:
    """
    Converts raw financial ratios into a single normalised score (0-100).

    Why composite scoring instead of raw ratios?
        Interviewers don't want "P/E is 22 and debt/equity is 0.8."
        They want "this is a 68/100 quality stock." A composite score
        is actionable; raw ratios require interpretation.

        More importantly: you can't directly compare P/E to debt/equity —
        they're on different scales. Normalising to 0-100 makes them
        combinable into a weighted composite.

    Metrics used and why each:

    1. P/E Ratio (Price-to-Earnings):
        How much investors pay per dollar of earnings.
        Lower = cheaper relative to earnings (better value).
        High P/E can mean growth expectations OR overvaluation.
        We score: P/E < 15 = value, 15-30 = fair, > 50 = expensive.
        Negative P/E (company losing money) = 0 score.

    2. Revenue Growth (YoY):
        Is the business actually growing?
        Fundamental question before anything else.
        > 20% growth → high score. Shrinking revenue → low score.

    3. Debt-to-Equity:
        Financial leverage / risk of bankruptcy.
        High debt = fragile in downturns.
        < 0.5 = conservative. > 2.0 = highly levered.

    4. Profit Margin:
        How much of each revenue dollar becomes profit.
        SaaS companies: 20-30%+ margins. Retailers: 2-5%. 
        Negative margins = burning cash.

    Interview: "Why these four metrics?"
        → They cover the four fundamental dimensions:
          Valuation (P/E), Growth (revenue), Risk (D/E), Profitability (margin).
          Every CFA analyst would start with exactly these.

    Args:
        info: yfinance ticker.info dict (full financial data)

    Returns:
        Fundamental quality score 0-100
    """
    score = 50.0   # Start at neutral
    adjustments = 0

    # ── P/E RATIO ────────────────────────────────────────────────────────────
    pe = info.get("trailingPE") or info.get("forwardPE")
    if pe is not None and pe > 0:
        if pe < 15:
            score += 15     # Cheap relative to earnings
        elif pe < 25:
            score += 8      # Fairly valued
        elif pe < 40:
            score += 0      # Neutral
        elif pe < 60:
            score -= 8      # Expensive
        else:
            score -= 15     # Very expensive
        adjustments += 1
    elif pe is not None and pe < 0:
        score -= 20         # Negative earnings — significant penalty
        adjustments += 1

    # ── REVENUE GROWTH ───────────────────────────────────────────────────────
    rev_growth = info.get("revenueGrowth")   # YoY growth as decimal (0.20 = 20%)
    if rev_growth is not None:
        if rev_growth > 0.30:
            score += 15     # Hyper-growth
        elif rev_growth > 0.15:
            score += 10     # Strong growth
        elif rev_growth > 0.05:
            score += 5      # Moderate growth
        elif rev_growth > 0:
            score += 0      # Slow growth — neutral
        else:
            score -= 15     # Revenue declining — bad sign
        adjustments += 1

    # ── DEBT TO EQUITY ───────────────────────────────────────────────────────
    de_ratio = info.get("debtToEquity")   # Expressed as % in yfinance (multiply by 0.01)
    if de_ratio is not None:
        de_normalised = de_ratio * 0.01   # Convert to standard ratio
        if de_normalised < 0.3:
            score += 12     # Very low debt
        elif de_normalised < 0.7:
            score += 6      # Manageable debt
        elif de_normalised < 1.5:
            score += 0      # Neutral
        elif de_normalised < 2.5:
            score -= 8      # High leverage
        else:
            score -= 15     # Dangerously levered
        adjustments += 1

    # ── PROFIT MARGIN ────────────────────────────────────────────────────────
    margin = info.get("profitMargins")   # As decimal (0.20 = 20% margin)
    if margin is not None:
        if margin > 0.25:
            score += 12     # Excellent profitability
        elif margin > 0.10:
            score += 6      # Good margins
        elif margin > 0.02:
            score += 0      # Thin but positive
        elif margin > 0:
            score -= 5      # Very thin
        else:
            score -= 12     # Unprofitable
        adjustments += 1

    # Clip to valid range and round
    return round(max(0.0, min(100.0, score)), 2)


# ── SINGLE TICKER FETCH ───────────────────────────────────────────────────────
def fetch_ticker_fundamentals(ticker: str) -> Optional[dict]:
    """
    Fetches all quantitative data for one ticker and returns structured signals.

    yfinance provides two main objects:
        ticker.history() → OHLCV price data (DataFrame)
        ticker.info      → 100+ fundamental fields (dict)

    We pull 6 months of price history:
        - Enough for 30-day volatility and momentum (need 30+ days)
        - Enough to plot a price chart in the UI
        - Not so much that the download is slow

    Args:
        ticker: Stock symbol

    Returns:
        Structured dict with all quantitative signals, or None on failure
    """
    try:
        stock = yf.Ticker(ticker)

        # ── PRICE HISTORY ────────────────────────────────────────────────────
        # period="6mo" = 6 months of daily OHLCV
        # auto_adjust=True = prices adjusted for splits and dividends
        #   (without this, a 2:1 stock split looks like a 50% price crash)
        hist = stock.history(period="6mo", auto_adjust=True)

        if hist.empty or len(hist) < 30:
            logger.warning(f"{ticker}: insufficient price history")
            return None

        closes = hist["Close"]   # We only need closing prices for our indicators

        # ── CURRENT PRICE AND CHANGE ─────────────────────────────────────────
        current_price   = round(float(closes.iloc[-1]), 2)
        prev_close      = round(float(closes.iloc[-2]), 2)
        daily_change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

        # ── TECHNICAL INDICATORS ─────────────────────────────────────────────
        rsi        = compute_rsi(closes)
        volatility = compute_historical_volatility(closes)
        momentum   = compute_momentum(closes)

        # ── VOLUME ANALYSIS ──────────────────────────────────────────────────
        # 10-day avg volume vs 30-day avg volume
        # High recent volume relative to average → unusual activity in price too
        # Combines with Reddit spike detection as confirmation signal
        volumes         = hist["Volume"]
        avg_volume_10d  = round(float(volumes.tail(10).mean()), 0)
        avg_volume_30d  = round(float(volumes.tail(30).mean()), 0)
        volume_ratio    = round(avg_volume_10d / avg_volume_30d, 3) if avg_volume_30d > 0 else 1.0

        # ── FUNDAMENTALS ─────────────────────────────────────────────────────
        # ticker.info is a large dict — can take 1-2s to fetch
        # Contains: P/E, revenue, margins, debt, market cap, sector, etc.
        info = stock.info

        fundamental_score = compute_fundamental_score(info)

        # ── 30-DAY PRICE SERIES FOR UI CHART ─────────────────────────────────
        # Return last 30 days of closes as a list for the frontend to chart
        price_chart_data = [
            {"date": str(date.date()), "price": round(float(price), 2)}
            for date, price in closes.tail(30).items()
        ]

        return {
            "ticker":             ticker,
            "current_price":      current_price,
            "daily_change_pct":   daily_change_pct,
            "rsi":                rsi,               # 0-100, >70 overbought, <30 oversold
            "volatility":         volatility,         # Annualised, e.g. 0.45 = 45%
            "momentum_30d":       momentum,           # % return over 30 days
            "volume_ratio":       volume_ratio,       # Recent vol / baseline vol
            "fundamental_score":  fundamental_score,  # 0-100 composite quality score
            "market_cap":         info.get("marketCap", 0),
            "pe_ratio":           info.get("trailingPE") or info.get("forwardPE"),
            "revenue_growth":     info.get("revenueGrowth"),
            "profit_margin":      info.get("profitMargins"),
            "sector":             info.get("sector", "Unknown"),
            "price_chart":        price_chart_data,  # For UI
        }

    except Exception as e:
        logger.error(f"Failed to fetch fundamentals for {ticker}: {e}")
        return None


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────────
def fetch_all_fundamentals(universe: list = STOCK_UNIVERSE) -> Dict[str, dict]:
    """
    Fetches fundamentals for every ticker in the universe.

    Why not parallel/async here?
        yfinance uses requests under the hood and isn't async-safe.
        For 24 tickers at ~1-2s each = 24-48s total. Acceptable for a
        daily/hourly refresh cycle. Not acceptable for real-time — at
        that point you'd switch to a paid data provider (Bloomberg,
        Polygon.io) with proper async APIs.

        Interview: "What data provider would you use in production?"
        → Polygon.io ($29/month) for real-time + historical.
          Bloomberg Terminal API for institutional-grade data.
          yfinance is appropriate for a research prototype.

    Returns:
        Dict mapping ticker → fundamentals dict.
        Missing tickers logged but excluded (don't fail the whole run).
    """
    results = {}
    failed  = []

    for i, ticker in enumerate(universe):
        logger.info(f"Fetching fundamentals [{i+1}/{len(universe)}]: {ticker}")
        data = fetch_ticker_fundamentals(ticker)

        if data:
            results[ticker] = data
        else:
            failed.append(ticker)

    if failed:
        logger.warning(f"Failed to fetch fundamentals for: {failed}")

    # Summary statistics — useful for debugging signal quality
    if results:
        avg_vol = np.mean([r["volatility"] for r in results.values()])
        avg_rsi = np.mean([r["rsi"] for r in results.values()])
        logger.info(
            f"Fundamentals complete: {len(results)} tickers. "
            f"Avg vol: {avg_vol:.1%} | Avg RSI: {avg_rsi:.1f}"
        )

    return results