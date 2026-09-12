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

## Newly found during Phase 1 (characterized in tests)

- **`risk_classifier.apply_override_rules()`: rule 4 could silently undo
  rule 1.** The five override rules ran in a fixed sequence and each rule
  only looked at the tier produced by the previous one, not *why* it got
  there. Concretely: a stock with extreme volatility (`> 80%`, rule 1
  forces `Speculative`) and strong fundamentals (`> 80`, rule 4's "floor")
  got bumped from `Speculative` back up to `Moderate` by rule 4 immediately
  after rule 1 set it — rule 1's volatility floor didn't actually hold in
  that combination. **Fixed in Phase 2** — see the table below.
- **`sentiment_scorer.compute_composite_score()`'s `weight_conf_sum == 0`
  branch is dead code.** `fundamental_confidence` is hardcoded to `1.0`
  ("Fundamentals are hard data, always trust them"), so as long as
  `SCORE_WEIGHTS["fundamental_score"] > 0` (it's `0.20`), the denominator
  can never actually reach zero — the documented "no data at all → 50.0"
  fallback is unreachable through this function's current signature. When
  reddit/StockTwits confidence are both 0, the composite silently collapses
  to exactly the fundamental score instead. See
  `test_composite_score_collapses_to_fundamentals_when_sentiment_confidence_is_zero`
  in `tests/test_sentiment_scorer.py`. **Still open** — changing the
  weighting formula affects every score the app produces, so this needs an
  explicit product decision, unlike the rule-ordering fix above (which the
  existing rule-1 docstring already implied was the intended behavior).

## Phase 2 — CI & the rule-ordering fix (done, 2026-09-13)

| # | Issue | Fix |
|---|-------|-----|
| 12 | No CI workflow ran `pytest` automatically — tests existed and passed locally (Phase 1) but nothing enforced they kept passing on push/PR. | Added `.github/workflows/tests.yml`: installs `requirements.txt` + `requirements-dev.txt`, runs the import sanity check, then `pytest -v`, on every push/PR to `main`. Deliberately excludes `test_pipeline.py` (needs a real `GROQ_API_KEY` and hits live third-party APIs — not appropriate for CI). |
| 13 | `risk_classifier.apply_override_rules()` rule 4 could silently undo rule 1's extreme-volatility floor (see above). | Rule 1 is now a hard floor: when it fires, the function returns immediately instead of falling through to rules 2-5. It's the only rule that short-circuits — its own docstring already stated the volatility floor should apply "regardless of composite score," which implicitly meant regardless of fundamentals too. Regression test: `test_rule1_is_a_hard_floor_rule4_cannot_lift_it` in `tests/test_risk_classifier.py` (replaces the Phase 1 characterization test of the same bug). |

## Still open (Phase 3+ candidates)

- **`compute_composite_score()`'s dead fallback branch** (see above) — still
  needs a product decision before touching the weighting formula.
- **Requirements pins were verified to *install and import* cleanly
  together** (Phase 0) and the pipeline logic is covered by unit +
  mocked-integration tests running in CI (Phases 1-2), but nothing has
  exercised the real external APIs end-to-end (StockTwits, yfinance, Groq,
  DuckDuckGo) — no `GROQ_API_KEY` is available in this environment. Worth a
  live `python test_pipeline.py` run with a real key before calling this
  repo production-ready.
- CI only runs on GitHub's hosted runners for push/PR to `main` — no
  branch-protection rule requires the check to pass before merging (that's
  a repo-settings change, not something a commit can express).
