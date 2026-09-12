import pandas as pd
import pytest

from fundamentals import (
    compute_rsi,
    compute_historical_volatility,
    compute_momentum,
    compute_fundamental_score,
)


# ── compute_rsi ──────────────────────────────────────────────────────────────

def test_rsi_insufficient_data_returns_neutral_fallback():
    prices = pd.Series([100.0, 101.0, 102.0])   # far fewer than period+1
    assert compute_rsi(prices, period=14) == 50.0


def test_rsi_monotonically_increasing_is_high():
    prices = pd.Series([100.0 + i for i in range(20)])
    rsi = compute_rsi(prices, period=14)
    assert rsi == 100.0   # no losses at all -> max RSI


def test_rsi_monotonically_decreasing_is_low():
    prices = pd.Series([120.0 - i for i in range(20)])
    rsi = compute_rsi(prices, period=14)
    assert rsi == pytest.approx(0.0, abs=1e-6)   # no gains at all -> RSI == 0


def test_rsi_is_bounded_0_to_100():
    prices = pd.Series([100, 102, 99, 105, 101, 98, 110, 107, 103, 108, 112, 109, 115, 111, 118, 120])
    rsi = compute_rsi(pd.Series(prices, dtype=float), period=14)
    assert 0.0 <= rsi <= 100.0


# ── compute_historical_volatility ────────────────────────────────────────────

def test_volatility_insufficient_data_returns_fallback():
    prices = pd.Series([100.0, 101.0])
    assert compute_historical_volatility(prices, window=30) == 0.30


def test_volatility_of_flat_prices_is_zero():
    prices = pd.Series([100.0] * 35)
    assert compute_historical_volatility(prices, window=30) == 0.0


def test_volatility_increases_with_larger_swings():
    calm = pd.Series([100 + (i % 2) * 0.5 for i in range(35)], dtype=float)
    wild = pd.Series([100 + (i % 2) * 20 for i in range(35)], dtype=float)
    assert compute_historical_volatility(wild, window=30) > compute_historical_volatility(calm, window=30)


# ── compute_momentum ─────────────────────────────────────────────────────────

def test_momentum_insufficient_data_returns_zero():
    prices = pd.Series([100.0, 101.0])
    assert compute_momentum(prices, window=30) == 0.0


def test_momentum_positive_for_uptrend():
    prices = pd.Series([100.0] + [100.0] * 29 + [130.0])  # 31 points, up 30% at the end
    momentum = compute_momentum(prices, window=30)
    assert momentum == pytest.approx(0.30, rel=1e-3)


def test_momentum_negative_for_downtrend():
    prices = pd.Series([100.0] * 30 + [80.0])
    momentum = compute_momentum(prices, window=30)
    assert momentum == pytest.approx(-0.20, rel=1e-3)


# ── compute_fundamental_score ────────────────────────────────────────────────

def test_fundamental_score_empty_info_is_neutral():
    assert compute_fundamental_score({}) == 50.0


def test_fundamental_score_strong_company_scores_high():
    info = {
        "trailingPE": 12,          # cheap
        "revenueGrowth": 0.35,     # hyper-growth
        "debtToEquity": 20,        # 0.20 normalised -> very low debt
        "profitMargins": 0.30,     # excellent
    }
    score = compute_fundamental_score(info)
    assert score > 80.0


def test_fundamental_score_weak_company_scores_low():
    info = {
        "trailingPE": -5,          # negative earnings
        "revenueGrowth": -0.10,    # shrinking
        "debtToEquity": 300,       # 3.0 normalised -> dangerously levered
        "profitMargins": -0.05,    # unprofitable
    }
    score = compute_fundamental_score(info)
    assert score < 20.0


def test_fundamental_score_is_bounded_0_to_100():
    info = {"trailingPE": -1000, "revenueGrowth": -1.0, "debtToEquity": 10000, "profitMargins": -1.0}
    assert 0.0 <= compute_fundamental_score(info) <= 100.0
