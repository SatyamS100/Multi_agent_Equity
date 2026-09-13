import pytest

from sentiment_scorer import (
    normalise_reddit_sentiment,
    normalise_stocktwits_sentiment,
    normalise_rsi,
    normalise_volatility,
    compute_composite_score,
    get_trending_now,
)


# ── normalise_reddit_sentiment ──────────────────────────────────────────────

def test_reddit_sentiment_neutral_momentum_maps_to_half():
    score, _ = normalise_reddit_sentiment(
        mention_momentum=0.0, spike_detected=False, mentions_24h=0, avg_post_score=0.0
    )
    assert score == 0.5


def test_reddit_sentiment_max_momentum_maps_to_one():
    score, _ = normalise_reddit_sentiment(
        mention_momentum=1.0, spike_detected=False, mentions_24h=0, avg_post_score=0.0
    )
    assert score == 1.0


def test_reddit_sentiment_spike_bonus_applied():
    without_spike, _ = normalise_reddit_sentiment(
        mention_momentum=0.5, spike_detected=False, mentions_24h=0, avg_post_score=0.0
    )
    with_spike, _ = normalise_reddit_sentiment(
        mention_momentum=0.5, spike_detected=True, mentions_24h=0, avg_post_score=0.0
    )
    assert with_spike - without_spike == pytest.approx(0.15)


def test_reddit_sentiment_score_clipped_to_one():
    score, _ = normalise_reddit_sentiment(
        mention_momentum=1.0, spike_detected=True, mentions_24h=0, avg_post_score=5000.0
    )
    assert score == 1.0


def test_reddit_sentiment_confidence_buckets():
    _, conf_low = normalise_reddit_sentiment(0.0, False, mentions_24h=2, avg_post_score=0.0)
    _, conf_mid = normalise_reddit_sentiment(0.0, False, mentions_24h=9, avg_post_score=0.0)
    _, conf_high = normalise_reddit_sentiment(0.0, False, mentions_24h=29, avg_post_score=0.0)
    _, conf_max = normalise_reddit_sentiment(0.0, False, mentions_24h=30, avg_post_score=0.0)

    assert conf_low == 0.2
    assert conf_mid == 0.5
    assert conf_high == 0.8
    assert conf_max == 1.0


# ── normalise_stocktwits_sentiment ──────────────────────────────────────────

def test_stocktwits_sentiment_maps_neutral_to_half():
    score, _ = normalise_stocktwits_sentiment(sentiment_score=0.0, confidence=0.0, message_volume=0)
    assert score == 0.5


def test_stocktwits_sentiment_maps_full_bullish_to_one():
    score, _ = normalise_stocktwits_sentiment(sentiment_score=1.0, confidence=1.0, message_volume=30)
    assert score == 1.0


def test_stocktwits_confidence_boosted_by_volume():
    _, conf_no_volume = normalise_stocktwits_sentiment(sentiment_score=0.0, confidence=0.5, message_volume=0)
    _, conf_full_volume = normalise_stocktwits_sentiment(sentiment_score=0.0, confidence=0.5, message_volume=20)
    assert conf_full_volume > conf_no_volume
    assert conf_full_volume == 0.7  # 0.5 base + 0.2 volume modifier cap


def test_stocktwits_confidence_clipped_to_one():
    _, conf = normalise_stocktwits_sentiment(sentiment_score=0.0, confidence=1.0, message_volume=30)
    assert conf == 1.0


# ── normalise_rsi ────────────────────────────────────────────────────────────

def test_normalise_rsi_brackets():
    assert normalise_rsi(20) == 0.55    # oversold
    assert normalise_rsi(45) == 0.75    # neutral-healthy
    assert normalise_rsi(60) == 0.85    # best zone
    assert normalise_rsi(70) == 0.55    # getting extended
    assert normalise_rsi(80) == 0.35    # overbought
    assert normalise_rsi(95) == 0.15    # extremely overbought


def test_normalise_rsi_boundary_values():
    assert normalise_rsi(30) == 0.55
    assert normalise_rsi(65) == 0.85
    assert normalise_rsi(85) == 0.35


# ── normalise_volatility ─────────────────────────────────────────────────────

def test_normalise_volatility_brackets():
    assert normalise_volatility(0.10) == (0.9, "Low")
    assert normalise_volatility(0.25) == (0.7, "Moderate")
    assert normalise_volatility(0.45) == (0.4, "High")
    assert normalise_volatility(0.90) == (0.2, "Extreme")


# ── compute_composite_score ──────────────────────────────────────────────────

def test_composite_score_collapses_to_fundamentals_when_sentiment_confidence_is_zero():
    # Confirmed intentional design (see compute_composite_score's docstring
    # and BUGS.md): fundamental_confidence is hardcoded to 1.0, so when
    # reddit and StockTwits confidence are both 0, the sentiment/momentum/
    # spike terms contribute zero weight and the composite deliberately
    # collapses to exactly the fundamental score rather than a flat 50.0 —
    # trusting the one real signal (yfinance fundamentals) over an
    # artificial neutral guess when there's no social data at all.
    score = compute_composite_score(
        reddit_score=0.9, reddit_confidence=0.0,
        stocktwits_score=0.9, st_confidence=0.0,
        fundamental_score=62.0,
        mention_momentum=0.9, spike_detected=True,
    )
    assert score == pytest.approx(62.0)


def test_composite_score_all_bullish_beats_all_bearish():
    bullish = compute_composite_score(
        reddit_score=1.0, reddit_confidence=1.0,
        stocktwits_score=1.0, st_confidence=1.0,
        fundamental_score=90.0,
        mention_momentum=1.0, spike_detected=True,
    )
    bearish = compute_composite_score(
        reddit_score=0.0, reddit_confidence=1.0,
        stocktwits_score=0.0, st_confidence=1.0,
        fundamental_score=10.0,
        mention_momentum=-1.0, spike_detected=False,
    )
    assert bullish > bearish
    assert bullish > 80.0
    assert bearish < 20.0


def test_composite_score_bounded_0_to_100():
    score = compute_composite_score(
        reddit_score=1.0, reddit_confidence=1.0,
        stocktwits_score=1.0, st_confidence=1.0,
        fundamental_score=100.0,
        mention_momentum=1.0, spike_detected=True,
    )
    assert 0.0 <= score <= 100.0


def test_composite_score_low_confidence_signal_has_less_influence():
    # Same stocktwits_score (1.0 = max bullish) but very different
    # confidence — the low-confidence version should pull the composite
    # score down less towards "max bullish" than the high-confidence one,
    # because its weight is scaled down by confidence.
    high_conf = compute_composite_score(
        reddit_score=0.5, reddit_confidence=0.5,
        stocktwits_score=1.0, st_confidence=1.0,
        fundamental_score=50.0,
        mention_momentum=0.0, spike_detected=False,
    )
    low_conf = compute_composite_score(
        reddit_score=0.5, reddit_confidence=0.5,
        stocktwits_score=1.0, st_confidence=0.05,
        fundamental_score=50.0,
        mention_momentum=0.0, spike_detected=False,
    )
    assert high_conf > low_conf


# ── get_trending_now ─────────────────────────────────────────────────────────

def _ticker(ticker, spike, mentions_24h, momentum):
    return {
        "ticker": ticker,
        "spike_detected": spike,
        "mentions_24h": mentions_24h,
        "mention_momentum": momentum,
        "composite_score": 50.0,
    }


def test_get_trending_now_prioritises_spikes_by_mentions():
    scored = [
        _ticker("AAA", spike=True, mentions_24h=5, momentum=0.1),
        _ticker("BBB", spike=True, mentions_24h=20, momentum=0.1),
        _ticker("CCC", spike=False, mentions_24h=100, momentum=0.9),
    ]
    trending = get_trending_now(scored, n=2)
    assert [t["ticker"] for t in trending] == ["BBB", "AAA"]


def test_get_trending_now_backfills_with_momentum_when_few_spikes():
    scored = [
        _ticker("AAA", spike=True, mentions_24h=5, momentum=0.1),
        _ticker("BBB", spike=False, mentions_24h=1, momentum=0.9),
        _ticker("CCC", spike=False, mentions_24h=1, momentum=0.2),
    ]
    trending = get_trending_now(scored, n=2)
    assert [t["ticker"] for t in trending] == ["AAA", "BBB"]


def test_get_trending_now_respects_n():
    scored = [_ticker(f"T{i}", spike=True, mentions_24h=i, momentum=0.0) for i in range(10)]
    trending = get_trending_now(scored, n=3)
    assert len(trending) == 3
