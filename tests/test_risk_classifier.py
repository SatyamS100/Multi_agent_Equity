from risk_classifier import (
    classify_by_score,
    apply_override_rules,
    compute_signal_strength,
    generate_quick_summary,
    classify_ticker,
    classify_all_tickers,
    TIER_ORDER,
)


# ── classify_by_score ────────────────────────────────────────────────────────

def test_classify_by_score_tier_boundaries():
    assert classify_by_score(0) == "Speculative"
    assert classify_by_score(29) == "Speculative"
    assert classify_by_score(30) == "Aggressive"
    assert classify_by_score(44) == "Aggressive"
    assert classify_by_score(45) == "Moderate"
    assert classify_by_score(64) == "Moderate"
    assert classify_by_score(65) == "Conservative"
    assert classify_by_score(100) == "Conservative"


def test_classify_by_score_out_of_range_falls_back_to_speculative():
    # RISK_TIERS bottoms out at 0 — a negative score matches no bracket
    # and should hit the fallback branch, not raise.
    assert classify_by_score(-5) == "Speculative"


# ── apply_override_rules ─────────────────────────────────────────────────────

def test_rule1_extreme_volatility_forces_speculative():
    # fundamental_score kept <= 80 and sentiment_score outside [-0.1, 0.1]
    # so rule 4 (strong-fundamentals floor) and rule 5 (mixed-sentiment
    # downgrade) can't also fire and mask what we're actually testing.
    tier, rules = apply_override_rules(
        initial_tier="Conservative", volatility=0.85, fundamental_score=50,
        rsi=50, spike_detected=False, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Speculative"
    assert len(rules) == 1
    assert "Extreme volatility" in rules[0]


def test_rule2_weak_fundamentals_plus_spike_forces_speculative():
    tier, rules = apply_override_rules(
        initial_tier="Moderate", volatility=0.30, fundamental_score=10,
        rsi=50, spike_detected=True, sentiment_score=0.0, has_llm=False,
    )
    assert tier == "Speculative"
    assert any("pump risk" in r for r in rules)


def test_rule2_does_not_fire_without_spike():
    tier, rules = apply_override_rules(
        initial_tier="Moderate", volatility=0.30, fundamental_score=10,
        rsi=50, spike_detected=False, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Moderate"
    assert rules == []


def test_rule4_can_override_rule1_when_fundamentals_are_strong():
    # Characterization test: rules run in sequence (1 -> 2 -> 3 -> 4 -> 5)
    # and each later rule only looks at the *current* tier, not which rule
    # produced it. So an extreme-volatility stock with fundamental_score > 80
    # gets forced to Speculative by rule 1, then immediately pulled back up
    # to Moderate by rule 4's "strong fundamentals floor" — rule 1's
    # volatility floor does not actually stick in this case. Documented
    # here because it reads as a bug at a glance; see BUGS.md.
    tier, rules = apply_override_rules(
        initial_tier="Conservative", volatility=0.85, fundamental_score=90,
        rsi=50, spike_detected=False, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Moderate"
    assert len(rules) == 2


def test_rule3_overbought_spike_downgrades_one_tier():
    tier, rules = apply_override_rules(
        initial_tier="Conservative", volatility=0.30, fundamental_score=70,
        rsi=85, spike_detected=True, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Moderate"
    assert any("overbought" in r for r in rules)


def test_rule4_strong_fundamentals_floor_is_moderate():
    tier, rules = apply_override_rules(
        initial_tier="Speculative", volatility=0.30, fundamental_score=85,
        rsi=50, spike_detected=False, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Moderate"
    assert any("Strong fundamentals" in r for r in rules)


def test_rule4_does_not_downgrade_conservative():
    tier, rules = apply_override_rules(
        initial_tier="Conservative", volatility=0.30, fundamental_score=85,
        rsi=50, spike_detected=False, sentiment_score=0.5, has_llm=False,
    )
    assert tier == "Conservative"
    assert rules == []


def test_rule5_mixed_sentiment_downgrades_one_tier():
    tier, rules = apply_override_rules(
        initial_tier="Moderate", volatility=0.30, fundamental_score=50,
        rsi=50, spike_detected=False, sentiment_score=0.05, has_llm=False,
    )
    assert tier == "Aggressive"
    assert any("Contradictory sentiment" in r for r in rules)


def test_rule5_does_not_fire_on_aggressive_or_speculative():
    tier, rules = apply_override_rules(
        initial_tier="Aggressive", volatility=0.30, fundamental_score=50,
        rsi=50, spike_detected=False, sentiment_score=0.0, has_llm=False,
    )
    assert tier == "Aggressive"
    assert rules == []


def test_no_rules_fire_on_a_clean_moderate_case():
    tier, rules = apply_override_rules(
        initial_tier="Moderate", volatility=0.30, fundamental_score=50,
        rsi=50, spike_detected=False, sentiment_score=0.4, has_llm=False,
    )
    assert tier == "Moderate"
    assert rules == []


# ── compute_signal_strength ──────────────────────────────────────────────────

def test_signal_strength_high():
    assert compute_signal_strength({"composite_score": 70, "sentiment_confidence": 0.8}) == "High"


def test_signal_strength_medium():
    assert compute_signal_strength({"composite_score": 45, "sentiment_confidence": 0.5}) == "Medium"


def test_signal_strength_low():
    assert compute_signal_strength({"composite_score": 20, "sentiment_confidence": 0.1}) == "Low"


def test_signal_strength_high_score_but_low_confidence_is_not_high():
    # High composite score alone isn't enough — needs confidence too.
    assert compute_signal_strength({"composite_score": 90, "sentiment_confidence": 0.1}) == "Low"


# ── generate_quick_summary ───────────────────────────────────────────────────

def test_quick_summary_includes_spike_and_tier():
    summary = generate_quick_summary({
        "spike_detected": True, "rsi": 50, "momentum_30d": 0.0, "st_bull_ratio": 0.5, "fundamental_score": 50,
    }, tier="Aggressive")
    assert summary.startswith("Aggressive")
    assert "Spike detected" in summary


def test_quick_summary_flags_overbought_and_strong_fundamentals():
    summary = generate_quick_summary({
        "spike_detected": False, "rsi": 82, "momentum_30d": 0.20, "st_bull_ratio": 0.8, "fundamental_score": 80,
    }, tier="Conservative")
    assert "overbought" in summary
    assert "+20%" in summary
    assert "bullish" in summary
    assert "Strong fundamentals" in summary


# ── classify_ticker / classify_all_tickers ──────────────────────────────────

def _ticker_data(**overrides):
    base = {
        "ticker": "AAPL",
        "composite_score": 55.0,
        "volatility": 0.30,
        "fundamental_score": 50.0,
        "rsi": 50.0,
        "spike_detected": False,
        # classify_ticker() maps this to sentiment_score = blended*2-1 for
        # the override rules. 0.8 -> 0.6, clear of the [-0.1, 0.1] band that
        # triggers rule 5's mixed-sentiment downgrade, so these fixtures
        # exercise classify_by_score()'s tier alone unless a test
        # deliberately overrides it.
        "blended_sentiment": 0.8,
        "has_llm_analysis": False,
    }
    base.update(overrides)
    return base


def test_classify_ticker_enriches_with_tier_metadata():
    result = classify_ticker(_ticker_data())
    assert result["risk_tier"] == "Moderate"
    assert result["ticker"] == "AAPL"
    assert "tier_emoji" in result
    assert "tier_color" in result
    assert "quick_summary" in result


def test_classify_all_tickers_groups_by_tier_and_includes_flat_list():
    tickers = [
        _ticker_data(ticker="AAA", composite_score=90, fundamental_score=90),
        _ticker_data(ticker="BBB", composite_score=10, fundamental_score=10, volatility=0.9),
    ]
    grouped = classify_all_tickers(tickers)

    assert set(TIER_ORDER).issubset(grouped.keys())
    assert "_all" in grouped
    assert len(grouped["_all"]) == 2
    # _all should be sorted by composite score descending
    assert [t["ticker"] for t in grouped["_all"]] == ["AAA", "BBB"]
