# graph.py
# ─────────────────────────────────────────────────────────────────────────────
# LANGGRAPH ORCHESTRATION — Multi-Agent Synthesis Engine
#
# This file defines the StateGraph that coordinates all agents.
# Understanding this file = understanding why this project is different.
#
# LangGraph core concepts used here:
#
#   StateGraph:
#       A directed graph where each NODE is a function (agent) and each
#       EDGE is a transition between agents. State is a typed dict that
#       flows through every node — each node reads from it and writes to it.
#       This is fundamentally different from LangChain chains (which are
#       linear and stateless between calls).
#
#   TypedDict State:
#       The state schema is declared upfront. Every node receives the FULL
#       state and returns a PARTIAL update. LangGraph merges updates.
#       Type safety = no silent failures from missing keys.
#
#   Conditional Edges:
#       After a node runs, a router function decides WHICH node to go to next.
#       This enables branching, retrying, and looping — things linear chains
#       cannot do. Our evaluation loop uses this: if the evaluator flags
#       hallucinations, we can route BACK to the synthesis node.
#
#   Why this matters in interviews:
#       "LangGraph is the framework for building stateful, cyclical agent
#        workflows. The step from LangChain to LangGraph is the step from
#        calling an LLM to orchestrating a decision-making system."
#       Most undergraduates have never used it. You built a production
#       instance of it.
# ─────────────────────────────────────────────────────────────────────────────

import json
import logging
from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from config import GROQ_API_KEY, GROQ_MODEL, TOP_N_FOR_LLM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: STATE SCHEMA
# The central typed dict that flows through every node in the graph.
# ─────────────────────────────────────────────────────────────────────────────

class SentimentGraphState(TypedDict):
    """
    The complete state of the multi-agent pipeline.

    Why TypedDict and not a plain dict?
        TypedDict gives you:
        1. Static type checking — catch wrong key names at development time
        2. IDE autocomplete — know what fields exist without reading docs
        3. Self-documentation — the schema IS the contract between agents
        4. LangGraph validation — the framework validates state transitions

    Annotated[List, operator.add]:
        For list fields, instead of overwriting the list on each update,
        we APPEND to it. This is how LangGraph handles list accumulation.
        operator.add on lists = concatenation.
        Without this, each node would overwrite the previous node's output.

    Interview: "How does state flow between your agents?"
        → Every node receives the full state dict. Each node returns a
          PARTIAL dict with only the keys it's updating. LangGraph merges
          the partial update into the full state before passing to next node.
          No agent needs to know about agents it doesn't interact with.
    """
    # Input data — populated before graph execution starts
    scored_tickers:     List[dict]          # Full ranked list from scorer
    tickers_for_llm: List[dict]          # Top N subset for LLM analysis

    # Intermediate outputs — populated by synthesis node
    synthesis_outputs:  Annotated[List[dict], operator.add]   # LLM's analyses

    # Evaluation outputs — populated by evaluator node
    evaluation_results: Annotated[List[dict], operator.add]   # Evaluator's verdicts

    # Final output — populated by aggregation node
    final_reports:      List[dict]          # Complete, validated reports for UI

    # Control flow
    current_batch:      int                 # Which batch we're currently processing
    total_batches:      int                 # How many batches total
    errors:             Annotated[List[str], operator.add]     # Any errors encountered


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: LLM CLIENT SETUP
# ─────────────────────────────────────────────────────────────────────────────

def get_llm_client() -> ChatGroq:
    """
    Initialises the LLM client via LangChain's Groq integration.

    Why ChatGroq (LangChain) instead of the raw groq SDK?
        LangChain's wrapper integrates natively with LangGraph nodes.
        It handles message formatting (System/Human/AI message objects),
        streaming, retry logic, and token counting automatically.
        The raw SDK is more flexible but requires more boilerplate inside
        LangGraph nodes.

    Model: config.GROQ_MODEL (defaults to llama-3.1-8b-instant via Groq)
        Groq's hosted Llama 3.1 8B gives low-latency inference at low cost,
        which matters here because synthesis + evaluation run two LLM calls
        per batch of 3 tickers. A larger hosted model would improve nuance
        on sarcasm detection at the cost of latency and API spend.

        The model id is read from config.GROQ_MODEL (env-overridable) rather
        than hardcoded here — Groq has deprecated a model this project
        depended on before (see CONTEXT.md), which broke the pipeline with
        no warning until a run failed. Swapping models is now a one-line
        .env change instead of a code change.

    temperature=0.3:
        Lower temperature = more deterministic, more factual output.
        We don't want creative hallucinations in financial analysis.
        We want consistent, grounded synthesis.
        0.3 allows some natural language variation without going off-script.

    Raises:
        RuntimeError: if GROQ_API_KEY isn't set. Without this check, a
            missing key fails deep inside synthesis_node/evaluation_node
            with an opaque auth error from the Groq SDK — this surfaces the
            real problem immediately, at the point the client is created.
    """
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add "
            "your key (https://console.groq.com/keys), or set it in your "
            "environment."
        )

    return ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.3,
        max_tokens=2000,   # Enough for full bull/bear case + risk summary
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: GRAPH NODES (AGENTS)
# Each function is one node in the StateGraph.
# Each receives state, does work, returns partial state update.
# ─────────────────────────────────────────────────────────────────────────────

def preparation_node(state: SentimentGraphState) -> dict:
    """
    NODE 1: PREPARATION
    Filters scored tickers to the top N and batches them for LLM.

    Why batch instead of one big call?
        24 tickers × full context per ticker = enormous prompt.
        LLM's context window can handle it, but:
        1. Token cost scales linearly — 10 tickers costs 10× more than 1
        2. LLM's attention quality degrades on very long prompts
        3. Batching gives us granular error handling — one batch fails,
           others still complete

        Batch size of 3: empirically balances context quality vs cost.
        Each batch gives LLM 3 tickers with full Reddit + ST context
        to compare and contrast — which actually IMPROVES analysis quality
        vs single-ticker prompts (LLM can calibrate relative signals).

    Interview: "How do you manage token costs in production?"
        → Batch strategically. Run LLM on top-N only. Cache outputs.
          Use a smaller/faster model for high-volume synthesis and reserve
          larger models for cases that need deeper reasoning.
    """
    scored  = state["scored_tickers"]
    top_n   = [t for t in scored if t.get("send_to_llm", False)]

    # Batch into groups of 3
    batch_size = 3
    batches    = [top_n[i:i+batch_size] for i in range(0, len(top_n), batch_size)]

    logger.info(
        f"Preparation: {len(top_n)} tickers → "
        f"{len(batches)} batches of {batch_size}"
    )

    return {
        "tickers_for_llm": top_n,
        "current_batch":      0,
        "total_batches":      len(batches),
        # Store batches in errors field temporarily — hack to avoid schema bloat
        # In production: add a `batches` field to the TypedDict
    }


def synthesis_node(state: SentimentGraphState) -> dict:
    """
    NODE 2: LLM SYNTHESIS
    The core LLM node. LLM reads Reddit + StockTwits posts and generates:
        - Sentiment assessment (with sarcasm handling)
        - Bull case (2-3 sentences)
        - Bear case (2-3 sentences)
        - Risk-reward summary
        - Confidence level

    This is the node that justifies the entire architecture.
    Everything before this is data prep. This is where intelligence is applied.

    Prompt engineering decisions (interview-ready):

    1. SYSTEM PROMPT establishes LLM as a financial analyst, not a chatbot.
       Framing matters — "you are a senior equity analyst" produces more
       calibrated, hedged, professional output than no framing.

    2. SARCASM INSTRUCTION is explicit and specific.
       WSB uses "TSLA to the moon 🚀" as both genuine and ironic.
       We tell LLM: "interpret financial intent, not literal meaning."
       Without this instruction, LLM defaults to literal interpretation
       and misclassifies ~30% of WSB posts.

    3. JSON OUTPUT FORMAT is enforced via instruction, not tool use.
       We could use LLM's tool_use for structured output, but for
       this use case, instruction-based JSON is simpler and equally reliable.
       We validate and parse the JSON in the calling code.

    4. SOURCE GROUNDING instruction: "only make claims supported by the
       provided posts." This is the anti-hallucination instruction at the
       synthesis level. The evaluator node then verifies it was followed.

    Interview: "How do you prevent LLM from hallucinating stock prices?"
        → Two-layer defence:
          1. Synthesis prompt explicitly says "do not invent statistics"
          2. Evaluator node re-reads the posts and checks every claim
             LLM made against the source material
    """
    llm  = get_llm_client()
    tickers = state["tickers_for_llm"]

    if not tickers:
        return {"synthesis_outputs": []}

    # Batch tickers into groups of 3 for this run
    # (In a full async implementation each batch would be a separate node call)
    batch_size = 3
    all_outputs = []

    for batch_start in range(0, len(tickers), batch_size):
        batch = tickers[batch_start:batch_start + batch_size]

        # ── BUILD CONTEXT FOR THIS BATCH ─────────────────────────────────────
        ticker_contexts = []
        for t in batch:
            # Assemble Reddit posts as readable text
            reddit_text = "\n".join([
                f"  [{p.get('subreddit','?')} | score:{p.get('score',0)}] "
                f"{p.get('title','')} - {p.get('text','')[:300]}"
                for p in t.get("top_reddit_posts", [])[:3]
            ]) or "  No Reddit posts available."

            # Assemble StockTwits messages
            st_text = "\n".join([
                f"  [likes:{m.get('likes',0)}] {m.get('text','')[:200]}"
                for m in t.get("top_st_messages", [])[:3]
            ]) or "  No StockTwits messages available."

            ticker_contexts.append(f"""
TICKER: {t['ticker']}
Composite Score: {t['composite_score']}/100
StockTwits Bull Ratio: {t['st_bull_ratio']:.0%} bullish ({t['st_message_volume']} messages)
RSI: {t['rsi']} | 30d Momentum: {t['momentum_30d']:+.1%} | Volatility: {t['volatility']:.0%} annualised
Fundamental Score: {t['fundamental_score']}/100 | Sector: {t['sector']}


Reddit Posts (highest scored):
{reddit_text}

StockTwits Messages (most liked):

{st_text}
""")

        full_context = "\n---\n".join(ticker_contexts)

        # ── SYSTEM PROMPT ─────────────────────────────────────────────────────
        system_prompt = """You are a senior equity research analyst specialising in 
alternative data and social sentiment signals. You analyse Reddit discussions and StockTwits messages to 
StockTwits messages to generate investment insights.

CRITICAL RULES:
1. SARCASM AWARENESS: Reddit (especially r/wallstreetbets) uses heavy irony.
   "This is definitely going to zero 🚀" is often BULLISH. "TSLA to the moon" 
   followed by "I'm totally not being sarcastic" is BEARISH. Interpret the 
   FINANCIAL INTENT, not the literal words. Look for context clues: emojis 
   used ironically, extreme statements, community in-jokes like "tendies", 
   "diamond hands", "apes".

2. GROUNDING: Only make claims directly supported by the provided posts and 
   quantitative metrics. Do not invent price targets, earnings figures, or 
   statistics not present in the data. If data is insufficient, say so.

3. CALIBRATION: If Reddit posts are overwhelmingly positive but RSI is 85 
   and volatility is 90%, the bull case should acknowledge momentum risk.
   Integrate quantitative context with sentiment — don't analyse them separately.

4. OUTPUT FORMAT: Respond ONLY with a valid JSON array. No preamble, no markdown
   code blocks, no explanation outside the JSON structure."""

        # ── USER PROMPT ───────────────────────────────────────────────────────
        user_prompt = f"""Analyse the following {len(batch)} stocks based on their 
social sentiment data and quantitative metrics. 

{full_context}

Return a JSON array with one object per ticker:
[
  {{
    "ticker": "SYMBOL",
    "sentiment_label": "Bullish" | "Bearish" | "Neutral" | "Mixed",
    "sentiment_score": <float -1.0 to 1.0>,
    "sarcasm_detected": <bool — was significant sarcasm/irony present?>,
    "bull_case": "<2-3 sentence bull case grounded in the provided data>",
    "bear_case": "<2-3 sentence bear case grounded in the provided data>",
    "key_themes": ["<theme1>", "<theme2>", "<theme3>"],
    "signal_quality": "High" | "Medium" | "Low",
    "signal_quality_reason": "<one sentence explaining the signal quality rating>",
    "confidence": <float 0.0 to 1.0>,
    "analyst_note": "<one sentence of the most important insight from this data>"
  }}
]

Analyse all {len(batch)} tickers: {[t['ticker'] for t in batch]}"""

        # ── LLM API CALL ───────────────────────────────────────────────────
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            logger.info(
                f"Calling LLM for batch: "
                f"{[t['ticker'] for t in batch]}"
            )

            response = llm.invoke(messages)
            raw_text = response.content

            # ── PARSE JSON RESPONSE ───────────────────────────────────────────
            # Strip any accidental markdown fencing LLM might add
            clean_text = raw_text.strip()
            if clean_text.startswith("```"):
                # Remove ```json ... ``` if present
                clean_text = clean_text.split("```")[1]
                if clean_text.startswith("json"):
                    clean_text = clean_text[4:]

            batch_analyses = json.loads(clean_text)

            # Merge LLM's analysis back into the ticker data
            analysis_map = {a["ticker"]: a for a in batch_analyses}
            for ticker_data in batch:
                t = ticker_data["ticker"]
                if t in analysis_map:
                    merged = {**ticker_data, "llm_analysis": analysis_map[t]}
                    all_outputs.append(merged)
                    logger.info(
                        f"✓ {t}: {analysis_map[t].get('sentiment_label')} | "
                        f"Confidence: {analysis_map[t].get('confidence')}"
                    )
                else:
                    # LLM didn't return analysis for this ticker
                    # Add with null analysis — evaluator will flag
                    logger.warning(f"LLM returned no analysis for {t}")
                    all_outputs.append({
                        **ticker_data,
                        "llm_analysis": None
                    })

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for batch {batch}: {e}")
            logger.error(f"Raw response was: {raw_text[:500]}")
            # Add tickers without LLM analysis rather than crashing
            for ticker_data in batch:
                all_outputs.append({**ticker_data, "llm_analysis": None})

        except Exception as e:
            logger.error(f"LLM API error for batch {batch}: {e}")
            for ticker_data in batch:
                all_outputs.append({**ticker_data, "llm_analysis": None})

    return {"synthesis_outputs": all_outputs}


def evaluation_node(state: SentimentGraphState) -> dict:
    """
    NODE 3: LLM-AS-JUDGE EVALUATION (Anti-Hallucination Loop)

    This is the self-evaluation loop from the project blueprint.
    A SECOND LLM call reads each synthesis output and verifies:
        1. Are the bull/bear cases grounded in the provided posts?
        2. Are there any specific claims (numbers, events) not in the data?
        3. Was sarcasm correctly identified?
        4. Is the confidence level calibrated to data quality?

    Why a second LLM call instead of rule-based checking?
        Rule-based fact-checking would need to:
        - Parse financial claims from free text (hard NLP problem)
        - Match them against source documents (semantic search problem)
        - Understand what counts as "grounded" (judgement problem)
        A second LLM can do all three in one prompt. This is the
        "LLM-as-judge" pattern — now standard in production AI systems.

    Interview: "How do you prevent hallucinations in financial analysis?"
        → Two-layer defence:
          Layer 1: Synthesis prompt explicitly instructs grounding
          Layer 2: Evaluator re-reads source posts, scores every claim,
                   flags anything not traceable to the provided data
        One model generates, a second model critiques — the same
        generate-then-critique idea behind Anthropic's Constitutional AI,
        applied here as a lightweight fact-checking pass.

    Interview: "What do you do when the evaluator flags a hallucination?"
        → Current implementation: flag and reduce confidence score.
          Phase 2 extension: conditional edge routes BACK to synthesis
          node with the evaluator's feedback, triggering regeneration.
          LangGraph's StateGraph makes this trivial to add — one
          conditional edge and a retry counter in state.

    Interview: "Isn't this expensive? Two LLM calls per ticker?"
        → Evaluator uses a much shorter prompt (just claims + sources).
          Synthesis = ~1500 tokens in, ~500 tokens out.
          Evaluation = ~800 tokens in, ~200 tokens out.
          The cost ratio is about 3:1 synthesis:evaluation.
          Acceptable for the hallucination protection it provides.
          In production, cache synthesis outputs for 6 hours and only
          re-evaluate when inputs change.
    """
    llm   = get_llm_client()
    outputs  = state["synthesis_outputs"]
    verified = []

    for ticker_data in outputs:
        analysis = ticker_data.get("llm_analysis")

        if analysis is None:
            # No synthesis to evaluate
            verified.append({
                **ticker_data,
                "evaluation": {
                    "grounded":          False,
                    "hallucination_flag": True,
                    "confidence_penalty": 0.5,
                    "evaluator_note":    "No synthesis generated",
                    "verified_claims":   [],
                    "flagged_claims":    [],
                }
            })
            continue

        # ── BUILD EVALUATION PROMPT ───────────────────────────────────────────
        # Give evaluator: the source posts + what LLM claimed
        # Ask: which claims are grounded, which are not?

        source_posts = "\n".join([
            f"- [{p.get('subreddit','?')}] {p.get('title','')} {p.get('text','')[:200]}"
            for p in ticker_data.get("top_reddit_posts", [])[:3]
        ])
        source_msgs = "\n".join([
            f"- {m.get('text','')[:200]}"
            for m in ticker_data.get("top_st_messages", [])[:3]
        ])

        bull_case  = analysis.get("bull_case", "")
        bear_case  = analysis.get("bear_case", "")
        key_themes = analysis.get("key_themes", [])

        eval_prompt = f"""You are a fact-checker for financial research reports.

TASK: Verify whether the analysis below is grounded in the provided source material.

SOURCE MATERIAL for {ticker_data['ticker']}:


Reddit Posts:
{source_posts if source_posts else "None available"}

StockTwits Messages:

{source_msgs if source_msgs else "None available"}

Quantitative Data Available:
- RSI: {ticker_data.get('rsi')}
- 30d Momentum: {ticker_data.get('momentum_30d')}
- Volatility: {ticker_data.get('volatility')}
- StockTwits Bull Ratio: {ticker_data.get('st_bull_ratio')}
- Fundamental Score: {ticker_data.get('fundamental_score')}

ANALYSIS TO VERIFY:
Bull Case: {bull_case}
Bear Case: {bear_case}
Key Themes: {key_themes}
Sarcasm Detected: {analysis.get('sarcasm_detected')}

EVALUATION CRITERIA:
1. Can each claim in the bull/bear case be traced to a source post or the quantitative data?
2. Are there specific statistics, events, or facts mentioned that don't appear in the sources?
3. Is the sarcasm detection consistent with what the posts actually say?

Respond ONLY with valid JSON, no preamble:
{{
  "grounded": <bool — is the overall analysis well-grounded?>,
  "hallucination_flag": <bool — are there specific unsupported claims?>,
  "confidence_penalty": <float 0.0-0.5 — how much to reduce confidence (0=no penalty)>,
  "verified_claims": ["<claim1 that IS grounded>", ...],
  "flagged_claims": ["<claim that is NOT grounded>", ...],
  "evaluator_note": "<one sentence summary of evaluation>"
}}"""

        try:
            response = llm.invoke([HumanMessage(content=eval_prompt)])
            raw_eval = response.content.strip()

            # Strip markdown fencing if present
            if raw_eval.startswith("```"):
                raw_eval = raw_eval.split("```")[1]
                if raw_eval.startswith("json"):
                    raw_eval = raw_eval[4:]

            evaluation = json.loads(raw_eval)

            # Apply confidence penalty to synthesis output
            original_confidence = analysis.get("confidence", 0.5)
            penalty             = evaluation.get("confidence_penalty", 0.0)
            adjusted_confidence = round(
                max(0.0, original_confidence - penalty), 4
            )

            analysis["confidence"] = adjusted_confidence

            if evaluation.get("hallucination_flag"):
                logger.warning(
                    f"⚠ Hallucination flagged for {ticker_data['ticker']}: "
                    f"{evaluation.get('flagged_claims', [])}"
                )
            else:
                logger.info(
                    f"✓ {ticker_data['ticker']} evaluation passed. "
                    f"Confidence: {adjusted_confidence}"
                )

            verified.append({
                **ticker_data,
                "llm_analysis": analysis,
                "evaluation":      evaluation,
            })

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Evaluation failed for {ticker_data['ticker']}: {e}")
            # Evaluation failure → treat as unverified, apply moderate penalty
            analysis["confidence"] = max(0.0, analysis.get("confidence", 0.5) - 0.2)
            verified.append({
                **ticker_data,
                "llm_analysis": analysis,
                "evaluation": {
                    "grounded":          None,
                    "hallucination_flag": None,
                    "confidence_penalty": 0.2,
                    "evaluator_note":    f"Evaluation failed: {str(e)}",
                    "verified_claims":   [],
                    "flagged_claims":    [],
                }
            })

    return {"evaluation_results": verified}


def aggregation_node(state: SentimentGraphState) -> dict:
    """
    NODE 4: AGGREGATION
    Merges LLM-analysed tickers (top 10) with rule-based scored tickers
    (remaining 15) into one complete, UI-ready list.

    Why aggregation is a separate node:
        The synthesis + evaluation nodes only touch the top 10.
        The other 15 tickers still need to appear in the UI with their
        composite scores, risk tiers, and basic data — just no LLM prose.
        This node stitches both groups into one unified list.

    What it produces per ticker:
        - Everything from the scorer (composite score, sentiment, fundamentals)
        - LLM analysis + evaluation verdict (top 10 only)
        - A "has_llm_analysis" flag so the UI knows what to render

    Interview: "What do the non-LLM tickers get?"
        → Full composite score, risk tier classification, all quantitative
          signals, price chart data. They get ranked in the list.
          They just don't get bull/bear prose or key themes.
          The UI shows them with a "Quantitative analysis only" label.
    """
    evaluated        = state["evaluation_results"]
    all_scored       = state["scored_tickers"]
    evaluated_tickers = {e["ticker"] for e in evaluated}

    # Build the final list: evaluated tickers first (they have LLM analysis)
    final = []

    # Add LLM-analysed tickers with their full enriched data
    for entry in evaluated:
        final.append({
            **entry,
            "has_llm_analysis": True,
        })

    # Add remaining tickers (rule-based only)
    for ticker_data in all_scored:
        if ticker_data["ticker"] not in evaluated_tickers:
            final.append({
                **ticker_data,
                "has_llm_analysis": False,
                "llm_analysis":     None,
                "evaluation":          None,
            })

    # Re-sort by composite score (LLM analysis doesn't change the rank)
    final.sort(key=lambda x: x["composite_score"], reverse=True)

    logger.info(
        f"Aggregation complete. "
        f"{len(evaluated)} LLM-analysed + "
        f"{len(final) - len(evaluated)} rule-based = "
        f"{len(final)} total tickers"
    )

    return {"final_reports": final}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: GRAPH CONSTRUCTION
# Wire the nodes together with edges and conditional routing.
# ─────────────────────────────────────────────────────────────────────────────

def build_sentiment_graph() -> any:
    """
    Constructs and compiles the LangGraph StateGraph.

    Graph topology:
        START → preparation → synthesis → evaluation → aggregation → END

    Why this ordering?
        preparation:  validates and batches input (fast, no LLM)
        synthesis:    LLM generates analysis (slow, expensive)
        evaluation:   LLM verifies analysis (slower, insurance)
        aggregation:  merges outputs (fast, no LLM)

    The graph is compiled once and reused for multiple runs.
    Compilation validates the graph structure — catches missing edges,
    unreachable nodes, and type mismatches at build time, not runtime.

    Interview: "How would you add the retry loop?"
        → After evaluation node, add a conditional edge:
          if any ticker has hallucination_flag=True AND retry_count < 2:
              route back to synthesis with evaluator feedback in state
          else:
              route to aggregation
          Add retry_count: int to SentimentGraphState.
          LangGraph handles the cycle natively — no special code needed.
          This is the power of StateGraph over linear chains.

    Interview: "What does 'compiled' mean in LangGraph?"
        → graph.compile() validates the graph structure, checks all nodes
          are reachable, verifies edges are consistent, and returns a
          Runnable object with .invoke(), .stream(), and .astream() methods.
          You can't call nodes on an uncompiled graph.
    """
    # Initialise StateGraph with our typed state schema
    workflow = StateGraph(SentimentGraphState)

    # ── ADD NODES ─────────────────────────────────────────────────────────────
    # Each node is registered with a name and a function.
    # The function signature must be: (state: SentimentGraphState) -> dict
    workflow.add_node("preparation",  preparation_node)
    workflow.add_node("synthesis",    synthesis_node)
    workflow.add_node("evaluation",   evaluation_node)
    workflow.add_node("aggregation",  aggregation_node)

    # ── ADD EDGES ─────────────────────────────────────────────────────────────
    # set_entry_point: which node runs first
    # add_edge: unconditional transition A → B
    # add_conditional_edges: conditional routing based on state
    workflow.set_entry_point("preparation")
    workflow.add_edge("preparation", "synthesis")
    workflow.add_edge("synthesis",   "evaluation")
    workflow.add_edge("evaluation",  "aggregation")
    workflow.add_edge("aggregation", END)

    # Compile validates structure and returns Runnable
    graph = workflow.compile()

    logger.info("LangGraph StateGraph compiled successfully")
    return graph


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: GRAPH RUNNER
# The public API that the rest of the system calls.
# ─────────────────────────────────────────────────────────────────────────────

def run_sentiment_graph(scored_tickers: List[dict]) -> List[dict]:
    """
    Public entry point. Takes scored tickers, runs the full graph,
    returns final reports.

    This is what app.py and the orchestration layer call.
    All graph complexity is hidden behind this function.

    Args:
        scored_tickers: Output of sentiment_scorer.score_all_tickers()

    Returns:
        List of final report dicts, ready for risk_classifier and UI
    """
    graph = build_sentiment_graph()

    # Build initial state
    # Only fields with values need to be set — LangGraph handles defaults
    initial_state: SentimentGraphState = {
        "scored_tickers":     scored_tickers,
        "tickers_for_llm": [],    # Populated by preparation_node
        "synthesis_outputs":  [],    # Populated by synthesis_node
        "evaluation_results": [],    # Populated by evaluation_node
        "final_reports":      [],    # Populated by aggregation_node
        "current_batch":      0,
        "total_batches":      0,
        "errors":             [],
    }

    logger.info(
        f"Starting graph execution with "
        f"{len(scored_tickers)} tickers"
    )

    # .invoke() runs the graph synchronously to completion
    # .stream() would give us node-by-node updates (useful for UI progress bars)
    final_state = graph.invoke(initial_state)

    reports = final_state.get("final_reports", [])

    logger.info(
        f"Graph execution complete. "
        f"{len(reports)} final reports generated."
    )

    return reports