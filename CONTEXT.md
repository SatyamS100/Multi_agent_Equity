# Project Context

## What this is

A portfolio/interview project: a multi-agent pipeline that scores a fixed
universe of 24 stocks by blending social sentiment, fundamentals, and LLM
synthesis, then classifies each into a risk tier for display in a small web
frontend. Many docstrings in the codebase are written in an "Interview:
..." Q&A style — that's intentional, this project doubles as interview
prep material for its author.

## History (from git log, oldest → newest)

1. **`2a085b0`** — Migrated off Streamlit + a Reddit-via-PRAW pipeline onto
   a FastAPI backend and a vanilla JS/HTML/CSS frontend. Reddit was dropped
   at this point.
2. **`dbdc04b`** — Reddit was restored, but via DuckDuckGo web search
   (`search_reddit_agent.py`) instead of the PRAW Reddit API — no Reddit
   API credentials needed. `ThreadPoolExecutor` parallelism was added so
   the three data-fetch agents (StockTwits, Reddit-search, fundamentals)
   run concurrently.
3. **`bf4879b`** / **`2d6ae93`** — Universe size tweaks during testing,
   eventually settled back to a fixed list (24 tickers as of this writing —
   see `config.py:STOCK_UNIVERSE`).
4. **`8137de4`** — The original LLM provider was Anthropic Claude
   (`langchain-anthropic`, model names like Sonnet). The project was
   migrated to Groq (`langchain-groq`, `llama-3.1-8b-instant`) via a
   find-and-replace script (`replace_claude.py`), then that model itself
   got decommissioned by Groq and was swapped to `llama-3.1-8b-instant`.
   This left behind stale comments referring to Claude model tiers
   (Sonnet/Haiku/Opus) and one factual error (attributing "Constitutional
   AI" to Groq instead of Anthropic) — cleaned up in the Phase 0 pass below.

## Phase 0 cleanup (this session, 2026-09-12)

The repo had drifted: dead one-off migration scripts left in the tree,
a corrupted (UTF-16) `.gitignore` that wasn't actually ignoring `.env`,
`__pycache__/*.pyc` files tracked in git, an unpinned/bloated
`requirements.txt` (streamlit, plotly, praw — all unused; duplicate
`uvicorn` line), CORS configured as `allow_origins=["*"]` +
`allow_credentials=True` (browsers reject that combination anyway), the
backend always returning HTTP 200 even on pipeline failure, unescaped
LLM-derived text going into `innerHTML` on the frontend, and
`stocktwits_agent.py` silently returning fake-neutral sentiment for every
ticker once StockTwits started blocking requests without a browser
`User-Agent` header (StockTwits is 35% of the sentiment weight — see
`SCORE_WEIGHTS` in `config.py`, so this was quietly degrading every run).

What changed — full list in the commit(s) this context was written
alongside; see [BUGS.md](BUGS.md) for the itemized before/after and what's
still open.

## Phase 1 — robustness & tests (this session, 2026-09-12)

Followed directly from the "Still open" list Phase 0 left in BUGS.md:

- Extended the fail-loud-on-majority-failure pattern (Phase 0 built it into
  `stocktwits_agent.py` alone) to `fundamentals.py` and
  `search_reddit_agent.py`, via a new shared `data_fetch_utils.py`. All
  three data-fetch agents now raise `DataFetchError` through the same
  helper instead of three separately-evolving implementations.
- Wired the previously-dead `price_chart` field into the frontend as an
  inline SVG sparkline, rather than deleting it or leaving it unused.
- Added a `tests/` suite (pytest) covering the pure scoring/classification/
  fundamentals functions plus a mocked FastAPI `TestClient` test for
  `backend.py` — none of it needs network access or a real `GROQ_API_KEY`.
  Writing these tests surfaced two real, subtle behaviors in the existing
  logic (an override-rule interaction in `risk_classifier.py`, a dead
  branch in `sentiment_scorer.compute_composite_score()`) — both
  characterized with tests and documented in BUGS.md rather than "fixed"
  silently, since the correct behavior in both cases is a product decision.
- Made the Groq model id configurable (`config.GROQ_MODEL`, env-overridable)
  instead of hardcoded in `graph.py`, and made `get_llm_client()` fail fast
  with a clear message if `GROQ_API_KEY` is missing, instead of failing
  deep inside a LangGraph node with an opaque SDK error.

Full before/after detail is in [BUGS.md](BUGS.md)'s Phase 1 table.

## Design notes worth knowing before touching scoring logic

- `config.py` is the single source of truth for tunable constants
  (universe, weights, thresholds). Don't hardcode thresholds elsewhere.
- `sentiment_scorer.py` confidence-weights each signal source before
  blending — a signal with low sample size (e.g. 1 StockTwits message)
  contributes less to the composite score even though its raw weight in
  `SCORE_WEIGHTS` is fixed. See `compute_composite_score()`.
- Only the top `TOP_N_FOR_LLM` (10) tickers by composite score get full LLM
  synthesis (`graph.py`); the rest get rule-based risk classification only.
  This is a cost/latency control, not a bug.
- `risk_classifier.py` applies override rules on top of the score-threshold
  tier (e.g. extreme volatility always forces Speculative regardless of
  score) — these encode domain knowledge the raw composite score can't.
