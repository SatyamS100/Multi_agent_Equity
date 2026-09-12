# risk_classifier.py
# ─────────────────────────────────────────────────────────────────────────────
# RISK CLASSIFIER — Investor Profile Mapping Layer
#
# Responsibility: Takes the final enriched ticker reports and assigns each
# to a risk tier (Conservative / Moderate / Aggressive / Speculative).
# Also generates the display metadata the frontend renders directly.
#
# Why risk tiers matter:
#   A composite score ranks stocks by signal quality. But signal quality
#   is not the same as risk-adjusted suitability.
#
#   Example:
#     GME: composite score 71 (huge Reddit spike, strong momentum signal)
#     MSFT: composite score 68 (consistent positive sentiment, strong fundamentals)
#
#   GME scores HIGHER on raw signal but is clearly not suitable for a
#   conservative investor. The risk classifier captures this distinction.
#
#   The composite score answers: "How strong is the signal?"
#   The risk tier answers:       "Who should act on this signal?"
#
# Classification philosophy:
#   Multi-factor with hard override rules.
#   Primary classification uses composite score thresholds from config.
#   Override rules handle edge cases the score can't capture:
#     - Extreme volatility always → Speculative (regardless of score)
#     - Negative fundamental score with spike → Speculative (pump risk)
#     - Very high RSI with spike → downgrade one tier (momentum exhaustion)
#
#   Interview: "Why not just use the composite score threshold directly?"
#   → The composite score is a SIGNAL QUALITY measure. A stock can have
#     an excellent signal (high confidence, strong momentum) but still be
#     inappropriate for conservative investors due to volatility or weak
#     fundamentals. The override rules encode domain knowledge that a
#     pure score can't capture.
# ─────────────────────────────────────────────────────────────────────────────

import logging
from typing import Dict, List, Tuple

from config import RISK_TIERS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: TIER DEFINITIONS AND DISPLAY METADATA
# ─────────────────────────────────────────────────────────────────────────────

# Full tier definitions with UI display properties
# Kept here (not config.py) because these are presentation-layer concerns,
# not system configuration concerns. Separation of concerns.
TIER_METADATA = {
    "Conservative": {
        "emoji":       "🛡️",
        "color":       "#2ECC71",    # Green
        "description": (
            "Strong fundamentals, low-to-moderate volatility, positive "
            "sentiment with high confidence. Suitable for risk-averse investors "
            "seeking quality signals with downside protection."
        ),
        "position_guidance": (
            "Standard position sizing. Signal quality is high and risk is managed."
        ),
        "typical_profile": (
            "Large-cap stocks with consistent earnings, moderate Reddit discussion, "
            "high StockTwits confidence, and RSI in healthy range (40-65)."
        ),
    },
    "Moderate": {
        "emoji":       "⚖️",
        "color":       "#3498DB",    # Blue
        "description": (
            "Decent fundamentals with meaningful sentiment momentum. "
            "Moderate volatility. Suitable for investors comfortable with "
            "some price swings in exchange for stronger signal strength."
        ),
        "position_guidance": (
            "Consider 75% of standard position size. Monitor RSI for "
            "extension risk."
        ),
        "typical_profile": (
            "Mid-to-large cap growth stocks with positive momentum, "
            "active community discussion, and acceptable fundamental quality."
        ),
    },
    "Aggressive": {
        "emoji":       "⚡",
        "color":       "#F39C12",    # Orange
        "description": (
            "Strong sentiment signal but elevated volatility or weaker "
            "fundamentals. Suitable for active traders with defined "
            "risk management and shorter time horizons."
        ),
        "position_guidance": (
            "50% of standard position size. Set clear stop-loss levels. "
            "High volatility means rapid moves in both directions."
        ),
        "typical_profile": (
            "High-beta growth stocks, recent earnings movers, or stocks "
            "with strong social momentum but stretched valuations."
        ),
    },
    "Speculative": {
        "emoji":       "🎲",
        "color":       "#E74C3C",    # Red
        "description": (
            "Extreme volatility, weak fundamentals, or pure social-momentum "
            "driven signal. High risk of rapid reversal. Suitable only for "
            "traders with high risk tolerance and strict position limits."
        ),
        "position_guidance": (
            "Maximum 25% of standard position size. Treat as lottery ticket. "
            "Spike-driven moves often reverse within 5-10 trading days."
        ),
        "typical_profile": (
            "Meme stocks, post-spike reversals, stocks with negative "
            "fundamentals and pure hype-driven sentiment."
        ),
    },
}

# Slider display order for the frontend's risk slider
# Left = most conservative, Right = most speculative
TIER_ORDER = ["Conservative", "Moderate", "Aggressive", "Speculative"]


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: PRIMARY CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_by_score(composite_score: float) -> str:
    """
    Primary classification using composite score thresholds from config.

    RISK_TIERS from config.py:
        Conservative: (65, 100)
        Moderate:     (45, 65)
        Aggressive:   (30, 45)
        Speculative:  (0,  30)

    This is the STARTING POINT. Override rules in classify_ticker()
    can move a stock to a different tier based on additional signals.

    Why these specific thresholds?
        65+ = strong signal across multiple sources with good confidence.
              Fundamentals typically pass minimum bar at this score.
        45-65 = meaningful signal but incomplete picture or moderate data.
        30-45 = signal exists but low confidence or weak fundamentals.
        0-30  = minimal signal, data-sparse, or contradictory signals.

    Interview: "How did you calibrate these thresholds?"
        → Set initially based on domain knowledge (what constitutes
          a high-confidence vs low-confidence signal). In production,
          calibrate against forward returns: what composite score
          threshold historically predicts positive 10-day returns?
          This connects directly to the Phase 2 backtesting layer.

    Args:
        composite_score: 0-100 composite from sentiment_scorer

    Returns:
        Initial tier string before override rules
    """
    for tier_name, (low, high) in RISK_TIERS.items():
        if low <= composite_score <= high:
            return tier_name
    return "Speculative"   # Fallback for scores outside all ranges


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: OVERRIDE RULES
# Domain knowledge encoded as hard rules that supersede score-based tier.
# ─────────────────────────────────────────────────────────────────────────────

def apply_override_rules(
    initial_tier:      str,
    volatility:        float,
    fundamental_score: float,
    rsi:               float,
    spike_detected:    bool,
    sentiment_score:   float,
    has_llm:        bool,
) -> Tuple[str, List[str]]:
    """
    Applies domain-knowledge override rules that can upgrade or downgrade
    the initial score-based tier classification.

    Returns both the final tier AND the list of rules that fired,
    so the UI can show the user WHY a stock is in its tier.

    Override Rules (in order of severity):

    RULE 1 — EXTREME VOLATILITY FLOOR (hard floor, short-circuits 2-5):
        If annualised volatility > 80%, classify as Speculative regardless
        of composite score — and return immediately, before rules 2-5 run.
        A stock moving ±5% daily is inappropriate for conservative investors
        no matter how strong the Reddit signal OR the fundamentals are.
        Interview: "What's the rationale?" → Position sizing. Conservative
        investors can't manage a 80%+ vol stock. Risk is in the instrument,
        not the signal — no other input should be able to override that.

        This is the only rule that short-circuits. Earlier, rules 2-5 ran
        unconditionally after rule 1, which meant rule 4 (strong
        fundamentals floor) could immediately undo rule 1: a stock with
        both extreme volatility and fundamental_score > 80 got bumped from
        Speculative back to Moderate one line later, silently defeating the
        volatility floor. Rule 1 is the one override in this function meant
        to be an absolute ceiling on risk tier, so it's the one rule that
        needs to win regardless of ordering.

    RULE 2 — FUNDAMENTAL FAILURE + SPIKE = PUMP RISK:
        If fundamental_score < 25 AND spike_detected = True, classify as
        Speculative. This is the GME/AMC pattern: weak company, massive
        Reddit hype. Social spike on a fundamentally weak stock = pump risk.
        The spike is more likely a pump than legitimate discovery.
        Interview: "How do you protect users from meme stock pumps?"
        → This rule. Fundamental floor prevents recommending garbage stocks
          just because WSB is talking about them.

    RULE 3 — OVERBOUGHT SPIKE DOWNGRADE:
        If RSI > 80 AND spike_detected = True, downgrade one tier.
        Reasoning: stock has ALREADY moved on the sentiment. By the time
        Reddit is spiking AND RSI is 80+, the easy money is made.
        Late-cycle sentiment + overbought price = elevated reversal risk.
        Interview: "Why RSI 80 and not 70?" → 70 fires too often on
        normal momentum stocks. 80 captures genuinely extended moves.

    RULE 4 — STRONG FUNDAMENTALS FLOOR:
        If fundamental_score > 80, minimum tier is Moderate regardless
        of composite score. High quality companies with any positive
        sentiment signal shouldn't be classified as Speculative or
        Aggressive. The fundamental quality is a safety net.

    RULE 5 — MIXED SENTIMENT PENALTY:
        If blended sentiment is near neutral (-0.1 to +0.1) despite
        mentions, the signal is contradictory (bulls and bears equally
        active). Downgrade one tier — conflicting signals are unreliable.

    Args:
        initial_tier:      Score-based classification
        volatility:        Annualised historical volatility
        fundamental_score: 0-100 quality score
        rsi:               14-period RSI
        spike_detected:    Reddit unusual activity flag
        sentiment_score:   Blended sentiment [-1, +1]
        has_llm:        Whether LLM analysis is available

    Returns:
        Tuple of (final_tier, list_of_rules_that_fired)
    """
    tier         = initial_tier
    rules_fired  = []

    # Helper: downgrade one tier in the TIER_ORDER list
    def downgrade(current: str) -> str:
        idx = TIER_ORDER.index(current)
        return TIER_ORDER[min(idx + 1, len(TIER_ORDER) - 1)]

    # Helper: upgrade one tier in the TIER_ORDER list
    def upgrade(current: str) -> str:
        idx = TIER_ORDER.index(current)
        return TIER_ORDER[max(idx - 1, 0)]

    # ── RULE 1: EXTREME VOLATILITY FLOOR (hard floor — returns immediately) ──
    if volatility > 0.80:
        if tier != "Speculative":
            tier = "Speculative"
            rules_fired.append(
                f"Extreme volatility ({volatility:.0%} annualised) → "
                f"reclassified to Speculative"
            )
        # Hard floor: no later rule (in particular rule 4's strong-
        # fundamentals floor) gets a chance to lift the tier back up.
        return tier, rules_fired

    # ── RULE 2: FUNDAMENTAL FAILURE + SPIKE = PUMP RISK ──────────────────────
    if fundamental_score < 25 and spike_detected:
        if tier not in ("Speculative", "Aggressive"):
            tier = "Speculative"
            rules_fired.append(
                f"Weak fundamentals (score: {fundamental_score:.0f}) combined "
                f"with Reddit spike → pump risk, reclassified to Speculative"
            )

    # ── RULE 3: OVERBOUGHT SPIKE DOWNGRADE ───────────────────────────────────
    if rsi > 80 and spike_detected and tier != "Speculative":
        original = tier
        tier      = downgrade(tier)
        rules_fired.append(
            f"RSI {rsi:.0f} (overbought) + Reddit spike → "
            f"late-cycle risk, downgraded from {original} to {tier}"
        )

    # ── RULE 4: STRONG FUNDAMENTALS FLOOR ────────────────────────────────────
    if fundamental_score > 80:
        current_idx = TIER_ORDER.index(tier)
        moderate_idx = TIER_ORDER.index("Moderate")
        if current_idx > moderate_idx:
            original = tier
            tier      = "Moderate"
            rules_fired.append(
                f"Strong fundamentals (score: {fundamental_score:.0f}) → "
                f"minimum tier Moderate, upgraded from {original}"
            )

    # ── RULE 5: MIXED SENTIMENT PENALTY ──────────────────────────────────────
    if -0.1 <= sentiment_score <= 0.1 and tier in ("Conservative", "Moderate"):
        original = tier
        tier      = downgrade(tier)
        rules_fired.append(
            f"Contradictory sentiment (score: {sentiment_score:+.2f}) → "
            f"signal reliability reduced, downgraded from {original} to {tier}"
        )

    return tier, rules_fired


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: SIGNAL STRENGTH AND DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def compute_signal_strength(ticker_data: dict) -> str:
    """
    Converts composite score + confidence into a human-readable signal label.

    Why a separate signal strength from risk tier?
        Risk tier = "who should trade this"
        Signal strength = "how much should we trust the signal"

        A Speculative stock can have HIGH signal strength:
        GME with 500 Reddit posts, 90% StockTwits bullish, spike detected →
        Speculative tier (weak fundamentals, extreme vol) but HIGH signal
        (the data is clear and consistent, just risky to act on).

        This distinction helps users understand: the signal is real,
        but the risk is high. That's different from: no signal exists.

    Labels:
        High:   composite > 65 AND confidence > 0.7
        Medium: composite > 40 AND confidence > 0.4
        Low:    everything else

    Args:
        ticker_data: Full enriched ticker dict

    Returns:
        "High" | "Medium" | "Low"
    """
    score      = ticker_data.get("composite_score", 0)
    confidence = ticker_data.get("sentiment_confidence", 0)

    if score > 65 and confidence > 0.7:
        return "High"
    elif score > 40 and confidence > 0.4:
        return "Medium"
    else:
        return "Low"


def generate_quick_summary(ticker_data: dict, tier: str) -> str:
    """
    Generates a one-line summary combining tier + key signals.
    This is the text that appears under each ticker card in the frontend.

    Examples:
        "Aggressive — Spike detected, RSI 78, bull momentum building on WSB"
        "Conservative — Consistent positive sentiment, strong fundamentals, low vol"
        "Speculative — Pure Reddit hype, negative fundamentals, extreme volatility"

    Why generate this here instead of in the UI?
        Business logic belongs in the data layer, not the presentation layer.
        The UI should just render strings, not compute them.
        This also makes the summary testable independently of the frontend.

    Args:
        ticker_data: Full enriched ticker dict
        tier:        Assigned risk tier

    Returns:
        One-line summary string
    """
    parts = [f"{tier}"]

    # Spike flag
    if ticker_data.get("spike_detected"):
        parts.append("📈 Spike detected")

    # RSI commentary
    rsi = ticker_data.get("rsi", 50)
    if rsi > 75:
        parts.append(f"RSI {rsi:.0f} (overbought)")
    elif rsi < 35:
        parts.append(f"RSI {rsi:.0f} (oversold)")

    # Momentum direction
    mom = ticker_data.get("momentum_30d", 0)
    if mom > 0.15:
        parts.append(f"+{mom:.0%} 30d momentum")
    elif mom < -0.10:
        parts.append(f"{mom:.0%} 30d momentum")

    # Dominant sentiment source
    st_bull = ticker_data.get("st_bull_ratio", 0.5)
    if st_bull > 0.70:
        parts.append(f"StockTwits {st_bull:.0%} bullish")
    elif st_bull < 0.35:
        parts.append(f"StockTwits {st_bull:.0%} bullish")

    # Fundamental quality signal
    fund = ticker_data.get("fundamental_score", 50)
    if fund > 70:
        parts.append("Strong fundamentals")
    elif fund < 30:
        parts.append("Weak fundamentals")

    return " — ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: MASTER CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

def classify_ticker(ticker_data: dict) -> dict:
    """
    Classifies one ticker and returns it enriched with tier + display metadata.

    This is the function that map()s over the full ticker list.

    Steps:
        1. Primary classification by composite score
        2. Override rules (can upgrade or downgrade)
        3. Signal strength label
        4. Quick summary string
        5. Full tier metadata (color, emoji, description, guidance)

    Args:
        ticker_data: Fully enriched ticker dict from aggregation_node

    Returns:
        ticker_data enriched with risk classification fields
    """
    # ── PRIMARY CLASSIFICATION ─────────────────────────────────────────────
    initial_tier = classify_by_score(ticker_data["composite_score"])

    # ── OVERRIDE RULES ─────────────────────────────────────────────────────
    final_tier, rules_fired = apply_override_rules(
        initial_tier      = initial_tier,
        volatility        = ticker_data.get("volatility", 0.30),
        fundamental_score = ticker_data.get("fundamental_score", 50.0),
        rsi               = ticker_data.get("rsi", 50.0),
        spike_detected    = ticker_data.get("spike_detected", False),
        sentiment_score   = ticker_data.get("blended_sentiment", 0.5) * 2 - 1,
        has_llm        = ticker_data.get("has_llm_analysis", False),
    )

    # Log if override fired
    if rules_fired:
        logger.info(
            f"{ticker_data['ticker']}: {initial_tier} → {final_tier} "
            f"(overrides: {rules_fired})"
        )

    # ── SIGNAL STRENGTH ────────────────────────────────────────────────────
    signal_strength = compute_signal_strength(ticker_data)

    # ── QUICK SUMMARY ──────────────────────────────────────────────────────
    quick_summary = generate_quick_summary(ticker_data, final_tier)

    # ── ENRICH AND RETURN ──────────────────────────────────────────────────
    return {
        **ticker_data,
        "risk_tier":          final_tier,
        "initial_tier":       initial_tier,          # For debugging/transparency
        "override_rules":     rules_fired,           # Why tier changed (if it did)
        "signal_strength":    signal_strength,       # High / Medium / Low
        "quick_summary":      quick_summary,         # One-liner for UI card
        "tier_emoji":         TIER_METADATA[final_tier]["emoji"],
        "tier_color":         TIER_METADATA[final_tier]["color"],
        "tier_description":   TIER_METADATA[final_tier]["description"],
        "position_guidance":  TIER_METADATA[final_tier]["position_guidance"],
        "typical_profile":    TIER_METADATA[final_tier]["typical_profile"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def classify_all_tickers(final_reports: List[dict]) -> Dict[str, List[dict]]:
    """
    Classifies every ticker and returns them grouped by risk tier.

    The grouped structure is what the frontend consumes directly.
    Each tier is a separate filterable group.

    Output structure:
    {
        "Conservative": [
            {ticker_data + risk_fields},
            ...
        ],
        "Moderate": [...],
        "Aggressive": [...],
        "Speculative": [...],
        "_all": [...]        # Flat list, sorted by composite score
                             # Underscore prefix = UI-internal, not a tier
    }

    Interview: "How does the risk slider work in the UI?"
        → User selects tiers (e.g. "Moderate" + "Aggressive").
          UI reads from this dict: results["Moderate"] + results["Aggressive"].
          Already sorted by composite score within each tier.
          No re-computation needed — classification is done once at pipeline end.

    Args:
        final_reports: Output of aggregation_node (full enriched ticker list)

    Returns:
        Dict mapping tier names → sorted list of classified ticker dicts
    """
    # Classify every ticker
    classified = [classify_ticker(t) for t in final_reports]

    # Sort all by composite score descending
    classified.sort(key=lambda x: x["composite_score"], reverse=True)

    # Group by tier
    grouped: Dict[str, List[dict]] = {tier: [] for tier in TIER_ORDER}

    for ticker in classified:
        tier = ticker["risk_tier"]
        grouped[tier].append(ticker)

    # Sort within each tier by composite score (already sorted globally,
    # but explicit sort within tier ensures correct ordering after grouping)
    for tier in TIER_ORDER:
        grouped[tier].sort(key=lambda x: x["composite_score"], reverse=True)

    # Add flat list for full-universe view
    grouped["_all"] = classified

    # ── LOG TIER DISTRIBUTION ────────────────────────────────────────────────
    distribution = {
        tier: len(grouped[tier]) for tier in TIER_ORDER
    }
    logger.info(f"Risk classification complete. Distribution: {distribution}")

    # Log Conservative tickers specifically — these are the "quality" signals
    if grouped["Conservative"]:
        cons_tickers = [t["ticker"] for t in grouped["Conservative"]]
        logger.info(f"Conservative tier: {cons_tickers}")

    # Log Speculative tickers — these need monitoring for pump risk
    if grouped["Speculative"]:
        spec_tickers = [t["ticker"] for t in grouped["Speculative"]]
        overrides    = [
            t["ticker"] for t in grouped["Speculative"]
            if t.get("override_rules")
        ]
        logger.info(f"Speculative tier: {spec_tickers}")
        if overrides:
            logger.warning(
                f"Override-driven Speculative reclassifications: {overrides}"
            )

    return grouped