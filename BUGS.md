# Known Issues / Bug Tracker

## Phase 0 — Unbreak it (done, 2026-09-12)

| # | Issue | Fix |
|---|-------|-----|
| 1 | `stocktwits_agent.py` sent no `User-Agent`/`Accept` headers — StockTwits' WAF returned 403s for every request, silently zeroing out 35% of the sentiment weight (`SCORE_WEIGHTS.sentiment_score`). | Added a browser-like `User-Agent` + `Accept: application/json` in `REQUEST_HEADERS`, sent on every request. |
| 2 | Total StockTwits fetch failure was invisible — every ticker fell back to a fake-neutral `sentiment_score: 0.0, bull_ratio: 0.5, confidence: 0.0` dict instead of surfacing the failure. | `fetch_all_stocktwits()` now raises `StockTwitsFetchError` if more than `MAX_FAILURE_RATIO` (50%) of the universe returns no data. |
| 3 | `.gitignore` was UTF-16-encoded garbage (`git ls-files` / diff showed mangled bytes) — `.env` was not reliably ignored, and `__pycache__/*.pyc` files were tracked in git. | Rewrote `.gitignore` as UTF-8 with proper patterns; `git rm -r --cached __pycache__`; added `.env.example`. |
| 4 | Six one-off migration/hack scripts were committed to the repo root (`replace_claude.py`, `fix_imports.py`, `reduce_universe.py`, `restore_universe.py`, `restore_graph.py`, `update_graph.py`) — dead weight, confusing to a new reader, and `fix_imports.py`/`replace_claude.py` did nothing (no-op string replacements). | Deleted all six. |
| 5 | Stale comments: Claude model tiers (Sonnet/Haiku/Opus) described in `graph.py` docstrings for a Groq model; `graph.py` misattributed "Constitutional AI" to Groq instead of Anthropic; `risk_classifier.py`/`sentiment_scorer.py`/`config.py`/`fundamentals.py` referred to a "Streamlit UI" that no longer exists; `# src/*.py` header comments implied a `src/` directory that doesn't exist; stale ticker-universe counts ("25 tickers") after the universe was trimmed to 24; a dead `SUBREDDITS`/`POSTS_PER_SUBREDDIT` config block described a 3-subreddit strategy `search_reddit_agent.py` never implements. | All rewritten to describe the code as it actually exists today. |
| 6 | CORS was `allow_origins=["*"]` + `allow_credentials=True` — an invalid combination browsers reject anyway, and needlessly permissive. Pipeline failures always returned HTTP 200 with `{"status": "error", ...}`, so callers had to inspect the body to detect failure. Frontend built HTML via template strings and `innerHTML` with LLM-generated `bull_case`/`bear_case`/`key_themes` text (which is derived from scraped Reddit/StockTwits post bodies) without escaping — a stored-XSS path if a post ever contained HTML that survived into the LLM output. | CORS now uses an explicit origin allowlist (`config.CORS_ORIGINS`, env-configurable) with `allow_credentials=False`. Backend raises `HTTPException(502, ...)` on pipeline failure. Frontend checks `response.ok` and reads `data.detail`. Added `escapeHtml()` in `script.js`, applied to every interpolated string field. |
| 7 | `requirements.txt` had unused deps (`streamlit`, `plotly`, `praw`, `ta` — none imported anywhere), a duplicated `uvicorn` line, and most packages unpinned. | Removed unused deps, deduplicated, pinned every package to a version verified to install and import cleanly together (see commit for the exact resolution). |

## Phase 1 — Robustness & tests (done, 2026-09-12)

| # | Issue | Fix |
|---|-------|-----|
| 8 | Partial fail-loud coverage: only `stocktwits_agent.py` raised on majority data-fetch failure. `fundamentals.py` silently dropped failed tickers, and `search_reddit_agent.py` never failed at all (a fully-blocked DuckDuckGo search just produced `mentions: 0` for every ticker, indistinguishable from genuinely quiet tickers). | Extracted the guard into a shared `data_fetch_utils.raise_if_too_many_failed()` (`DataFetchError`, `MAX_FAILURE_RATIO = 0.5`), used by all three agents. `search_reddit_agent.py` now tracks actual search *exceptions* separately from tickers with zero genuine results, so a quiet ticker still isn't treated as a failure. `stocktwits_agent.py` refactored onto the shared helper too (its local `StockTwitsFetchError` is gone — one exception type, one message format, one threshold, across all three agents). |
| 9 | `price_chart` was dead data on the wire — `fundamentals.py`/`sentiment_scorer.py` computed and forwarded a 30-day price series per ticker that `frontend/script.js` never rendered. | Added a dependency-free inline SVG sparkline (`buildSparkline()` in `script.js`) rendered on each ticker card, colored green/red by trend. No charting library added for one line per card. |
| 10 | No automated tests beyond the manual, network-dependent `test_pipeline.py`. | Added `tests/` (pytest): unit tests for the pure functions in `sentiment_scorer.py`, `risk_classifier.py`, `fundamentals.py`, and `data_fetch_utils.py` (no network calls), plus `tests/test_backend.py` — a FastAPI `TestClient` test that monkeypatches the three fetch agents and `run_sentiment_graph` to verify the success response shape, the 502-on-failure path, and CORS header behavior, all without hitting a real API or needing `GROQ_API_KEY`. Added `requirements-dev.txt` (pytest + httpx, pinned). Run with `pytest` from the repo root. |
| 11 | Groq model was hardcoded by name (`"llama-3.1-8b-instant"` in `graph.py`) — already broke once in this repo's history when Groq deprecated the previous model, with no startup check. `GROQ_API_KEY` wasn't validated either; a missing key failed deep inside `synthesis_node`/`evaluation_node` with an opaque SDK auth error. | Added `config.GROQ_MODEL` (env-overridable, defaults to `llama-3.1-8b-instant`) — swapping models after a future Groq deprecation is now a `.env` change, not a code change. `graph.get_llm_client()` now raises a clear `RuntimeError` immediately if `GROQ_API_KEY` is unset, instead of failing deep inside a node with a generic auth error. |

## Newly found during Phase 1 (characterized, not yet fixed)

- **`risk_classifier.apply_override_rules()`: rule 4 can silently undo rule
  1.** The five override rules run in a fixed sequence and each rule only
  looks at the tier produced by the previous one, not *why* it got there.
  Concretely: a stock with extreme volatility (`> 80%`, rule 1 forces
  `Speculative`) and strong fundamentals (`> 80`, rule 4's "floor") gets
  bumped from `Speculative` back up to `Moderate` by rule 4 immediately
  after rule 1 set it — rule 1's volatility floor doesn't actually hold in
  that combination. Pinned down as a characterization test
  (`test_rule4_can_override_rule1_when_fundamentals_are_strong` in
  `tests/test_risk_classifier.py`) rather than "fixed" here, since the
  right fix (should rule 1 be a hard floor no later rule can lift? should
  rule ordering matter at all?) is a product decision, not a bug fix.
- **`sentiment_scorer.compute_composite_score()`'s `weight_conf_sum == 0`
  branch is dead code.** `fundamental_confidence` is hardcoded to `1.0`
  ("Fundamentals are hard data, always trust them"), so as long as
  `SCORE_WEIGHTS["fundamental_score"] > 0` (it's `0.20`), the denominator
  can never actually reach zero — the documented "no data at all → 50.0"
  fallback is unreachable through this function's current signature. When
  reddit/StockTwits confidence are both 0, the composite silently collapses
  to exactly the fundamental score instead. See
  `test_composite_score_collapses_to_fundamentals_when_sentiment_confidence_is_zero`
  in `tests/test_sentiment_scorer.py`.

## Still open (Phase 2+ candidates)

- **Requirements pins were verified to *install and import* cleanly
  together** (Phase 0) and the pipeline logic is now covered by unit +
  mocked-integration tests (Phase 1), but nothing has exercised the real
  external APIs end-to-end (StockTwits, yfinance, Groq, DuckDuckGo) — no
  `GROQ_API_KEY` is available in this environment. Worth a live
  `python test_pipeline.py` run with a real key before calling this
  repo production-ready.
- The two "newly found" items above (rule ordering interaction, dead
  fallback branch) are documented but not fixed — need a product decision
  first, not just a code change.
- No CI workflow runs `pytest` automatically on push/PR yet — the tests
  exist and pass locally but nothing enforces they keep passing.
