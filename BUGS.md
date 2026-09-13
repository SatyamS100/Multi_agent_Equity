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
  in `tests/test_sentiment_scorer.py`. **Resolved in Phase 3 (kept as-is,
  by product decision)** — see the table below.

## Phase 2 — CI & the rule-ordering fix (done, 2026-09-13)

| # | Issue | Fix |
|---|-------|-----|
| 12 | No CI workflow ran `pytest` automatically — tests existed and passed locally (Phase 1) but nothing enforced they kept passing on push/PR. | Added `.github/workflows/tests.yml`: installs `requirements.txt` + `requirements-dev.txt`, runs the import sanity check, then `pytest -v`, on every push/PR to `main`. Deliberately excludes `test_pipeline.py` (needs a real `GROQ_API_KEY` and hits live third-party APIs — not appropriate for CI). |
| 13 | `risk_classifier.apply_override_rules()` rule 4 could silently undo rule 1's extreme-volatility floor (see above). | Rule 1 is now a hard floor: when it fires, the function returns immediately instead of falling through to rules 2-5. It's the only rule that short-circuits — its own docstring already stated the volatility floor should apply "regardless of composite score," which implicitly meant regardless of fundamentals too. Regression test: `test_rule1_is_a_hard_floor_rule4_cannot_lift_it` in `tests/test_risk_classifier.py` (replaces the Phase 1 characterization test of the same bug). |

## Phase 3 — Live verification (done, 2026-09-13)

The user supplied a real `GROQ_API_KEY`, unblocking the one item Phase 0-2
couldn't close: an actual end-to-end run against live StockTwits, yfinance,
DuckDuckGo, and Groq. It immediately paid for itself — three real,
previously-invisible bugs surfaced within the first two runs.

**Before touching code:** the key was found pasted into `.env.example`
(tracked by git) instead of `.env` (gitignored) — a one-file mix-up that
would have pushed a live credential to GitHub on the next commit. Caught
via `git diff` before anything was staged; nothing was ever committed or
pushed. Fixed by moving the key into a newly-created `.env` and restoring
`.env.example`'s placeholder. No exposure occurred, so no rotation was
needed, but it's the reason `.env.example` exists as a *template* — never
edit it with a real value, always copy it to `.env` first.

| # | Issue | Fix |
|---|-------|-----|
| 14 | `duckduckgo-search==6.3.7` picks a random TLS/browser-fingerprint preset from a hardcoded 33-entry list on every `DDGS()` construction; several of those presets (including `chrome_100`) are no longer supported by the `primp` version pip resolves today, crashing `search_reddit_agent.py` with `primp.BuilderError: Invalid impersonate: "chrome_100"` roughly 1 run in a handful. Confirmed live: the very first Phase 3 run hit it and the whole pipeline 502'd. | Bumped to `duckduckgo-search==8.1.1`, which fixed this exact issue upstream (now delegates fingerprint choice to `primp` itself via `impersonate="random"` instead of maintaining its own list that goes stale as `primp` evolves). Verified the `DDGS`/`.text()` API surface `search_reddit_agent.py` uses is unchanged, then re-ran the live pipeline — all 24 Reddit searches succeeded. |
| 15 | Groq deprecated `llama-3.1-8b-instant` — again (third time in this repo's history; see CONTEXT.md). Every synthesis/evaluation call 404'd with `model_not_found`. The pipeline didn't crash (graceful degradation was already in place from before this project's tracked history — failed batches get `llm_analysis: None`), but silently produced zero AI analysis for all 24 tickers while still reporting `status: success`. | Queried `GET https://api.groq.com/openai/v1/models` live to list currently-valid ids, smoke-tested `openai/gpt-oss-20b` with a real call, then set it as `config.GROQ_MODEL`'s new default. Re-ran the live pipeline — synthesis and evaluation both completed with real bull/bear cases rendered in the frontend. |
| 16 | `graph.py`'s `evaluation_node` fact-checks synthesis output against a "Quantitative Data Available" block that was missing `composite_score` and `sector` — two fields `synthesis_node`'s `ticker_contexts` *does* give the synthesis LLM and explicitly tells it to cite. Result: the evaluator flagged legitimate, data-grounded claims like "composite score of 98.15" as hallucinations on 8-9 of 10 tickers per run, since it had no way to verify a number it was never shown — a systematic false-positive rate, not occasional noise. | Added `composite_score` and `sector` to the evaluator's "Quantitative Data Available" block so it mirrors exactly what synthesis saw. Confirmed live: hallucination-flag rate dropped from 9/10 to 6/10 on the next run, and the remaining flags are for more specific/nuanced claims rather than blanket-flagging near everything. Documented in-code that this block must be kept in sync with `ticker_contexts` going forward. |
| 17 | `pytest` (bare invocation, no path) was silently discovering and importing root-level `test_pipeline.py` because it matches the default `test_*.py` glob — but that file is a manual smoke script with *unconditional module-level side effects* (`result = run_pipeline()` runs at import time, not inside a test function). Every `pytest` run — locally **and in CI** — was silently executing a real, partial pipeline run (StockTwits + Reddit + fundamentals always; LLM stage too once a real key existed) before collection even finished. This had been happening since Phase 1 and inflated every "pytest took ~40-60s" observation; it only became obvious in Phase 3 once a real `GROQ_API_KEY` made the *full* run complete instead of erroring out early, stretching a 2-4 second test suite to 200-250 seconds. | Added `pytest.ini` with `testpaths = tests`, scoping default discovery to the `tests/` directory only. Verified: collection time dropped from 200+s to ~4s, the suite runs in ~2s, and the earlier unexplained `duckduckgo_search` deprecation warning in pytest's own output (a symptom of the same leak — proof `DDGS()` was really being constructed during test runs) is gone. **This also means every CI run to date (Phase 2's) was doing this too** — the green checkmark was still valid (nothing failed), it was just doing several times more work than intended. |
| 18 | `sentiment_scorer.compute_composite_score()`'s dead "no data → 50.0" fallback branch (flagged Phase 1-2, needed a product decision). | **Decision: keep as-is.** `fundamental_confidence=1.0` is intentional — fundamentals are hard data (yfinance financials), worth trusting fully even when social sentiment is silent. Clarified the docstring and the corresponding test to state this is confirmed-intentional design, not a latent bug, so a future reader doesn't reopen the question without cause. |

Full live-run evidence (log excerpts, exact hallucination-flag counts,
model list from the Groq API) is in this session's transcript; the
summary above is what a future reader needs without re-deriving it.

## Phase 4 — dependency hygiene & universe fix (done, 2026-09-13)

Closed out the two concrete, low-risk items from Phase 3's "Still open"
list. Left the other two open — one needs live-run evidence before further
prompt tuning is justified, the other needs a GitHub repo-settings change
outside what a commit can express (see "Still open" below).

| # | Issue | Fix |
|---|-------|-----|
| 19 | `duckduckgo-search` is deprecated upstream in favor of a renamed `ddgs` package; 8.1.1 (Phase 3's fix for issue #14) still worked but was on a dead-end package. | Verified live that `ddgs==9.16.0`'s `DDGS().text(query, max_results=N)` API is unchanged (same `title`/`href`/`body` result keys) before touching code. Swapped `search_reddit_agent.py`'s import and `requirements.txt`'s pin from `duckduckgo-search==8.1.1` to `ddgs==9.16.0`, uninstalled the old package from the venv, and confirmed `pytest` still passes 64/64 with no `duckduckgo_search`/`ddgs` deprecation warning in the output. |
| 20 | `SQ` in `config.STOCK_UNIVERSE` has been delisted on Yahoo Finance since Square Inc. renamed to Block, Inc. and moved to ticker `XYZ` in December 2021 — `fetch_ticker_fundamentals` was correctly excluding it every run (not a bug, just dead weight in the universe). | Swapped `SQ` → `XYZ` in `config.STOCK_UNIVERSE` (same company, same "High Beta / Retail" category — not a universe redesign). Verified live via `yfinance.Ticker("XYZ")` that it resolves (`shortName: Block, Inc.`, `sector: Technology`) and returns 22 rows of price history before wiring it in. |
| 21 | **Found only by the live run, not by the API-shape check above**: `ddgs`'s default `backend="auto"` fans a single `.text()` call out to ~8 engines in parallel (DuckDuckGo, Google, Brave, Mojeek, Yahoo, Startpage, Wikipedia, Grokipedia) instead of querying DuckDuckGo alone like `duckduckgo-search` did. Across a 24-ticker loop this multiplies request volume ~8x, and several of those engines (Google, Brave, Mojeek) 429/403 almost immediately — the first live pipeline run after the issue #19 swap failed outright with 16/24 (67%) Reddit-search failures, tripping `raise_if_too_many_failed`'s 50% threshold exactly as designed. | Pinned `backend="duckduckgo"` explicitly in `ddgs.text()`'s call in `search_reddit_agent.py`, restricting it back to the single DuckDuckGo-only engine `duckduckgo-search` always used. Re-ran the live pipeline: failures dropped from 16/24 to 4/24 (17%, DuckDuckGo's own soft-throttle — occasional `202` responses — well under the 50% threshold), full run completed with `Status: success`. |

Verified, not just claimed: the very first live pipeline run after the
issue #19/#20 swap actually *failed* (issue #21) — the API-shape check
alone wasn't enough to catch a default-parameter behavior change. Only a
real 24-ticker end-to-end run surfaced it. After the issue #21 fix,
re-ran `test_pipeline.py` end-to-end against live StockTwits, yfinance,
`ddgs`-backed DuckDuckGo, and Groq: **`Status: success`, 229.27s, all 24
tickers classified** (10 LLM-analysed + 14 rule-based), `XYZ` fetched and
scored normally (StockTwits bullish, included in the Conservative tier),
risk-tier overrides fired correctly (`PLTR`/`MSTR`/`RBLX` → Speculative on
extreme volatility, `HOOD` → Aggressive on contradictory sentiment) — see
CONTEXT.md's Phase 4 section for the full narrative.

## Still open (Phase 5+ candidates)

- **The evaluator's remaining hallucination flags** (issue #16) still
  include some defensible-but-arguably-false-positives — e.g. flagging
  "all 30 StockTwits messages are bullish" as ungrounded when the evaluator
  was given "StockTwits Bull Ratio: 100%" and only sees 3 sample messages,
  not all 30, so it can't independently verify the claim even though it's
  a correct restatement of provided data. Worth a further prompt-engineering
  pass if evaluator-driven confidence penalties start looking systematically
  too harsh, but not chased further to avoid unvalidated whack-a-mole
  prompt tuning without fresh live-run evidence.
- CI only runs on GitHub's hosted runners for push/PR to `main` — no
  branch-protection rule requires the check to pass before merging. This is
  a GitHub repo-settings change (Settings → Branches → branch protection
  rules, or `gh api repos/{owner}/{repo}/branches/main/protection`), not
  something a commit can express — needs repo-admin action, done
  deliberately rather than as a drive-by from an agent session. **Attempted
  in Phase 4** via `gh api .../branches/main/protection -X PUT` — failed
  with `404 Not Found` because the authenticated account has `push` but not
  `admin` on this repo (confirmed via `gh api repos/{owner}/{repo} --jq
  .permissions`, which returned `"admin": false`). GitHub's branch-
  protection endpoint requires repo-admin, and returns 404 rather than 403
  when the caller lacks it. Needs either the repo owner to grant that
  account admin, or the owner to configure it directly via Settings →
  Branches → Add rule, requiring the `pytest` check on `main`.
