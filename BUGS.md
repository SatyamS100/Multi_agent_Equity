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

## Still open (Phase 1+ candidates)

- **Partial fail-loud coverage**: only `stocktwits_agent.py` raises on majority
  data-fetch failure. `fundamentals.py` (`fetch_all_fundamentals`) silently
  drops failed tickers (`sentiment_scorer.score_all_tickers` just skips
  tickers with no fundamentals — `if not fn: continue`), and
  `search_reddit_agent.py` never fails at all (a fully-blocked DuckDuckGo
  search just produces `mentions: 0` for every ticker, indistinguishable
  from genuinely quiet tickers). Same class of bug as issue #2 above,
  narrower blast radius since Reddit/fundamentals aren't the majority of
  `SCORE_WEIGHTS`.
- **`price_chart` is dead data on the wire**: `fundamentals.py` computes and
  `sentiment_scorer.py` forwards a 30-day price series per ticker, but
  `frontend/script.js` never reads or renders it. Either wire it into the UI
  or stop computing it.
- **No automated tests** beyond `test_pipeline.py`, which is a manual,
  network-dependent smoke script (hits live StockTwits/yfinance/DuckDuckGo/
  Groq APIs) — not something CI can run reliably. No unit tests for the pure
  functions in `sentiment_scorer.py` / `risk_classifier.py` (e.g.
  `compute_composite_score`, `apply_override_rules`), which are easy to
  test in isolation since they take plain values, not network calls.
- **Groq model pinned by name** (`llama-3.1-8b-instant` in `graph.py`) —
  this has already broken once in this repo's history when Groq
  decommissioned the previous model. No fallback or startup check that the
  configured model is still valid.
- **`.env` was already missing/untracked before this cleanup** — good — but
  there's no runtime check that `GROQ_API_KEY` is actually set; a missing
  key fails deep inside `graph.py`'s `synthesis_node`/`evaluation_node`
  with a generic API error rather than a clear startup message.
- **Requirements pins were verified to *install and import* cleanly together
  in this session** (see `requirements.txt`), but not exercised end-to-end
  against the live StockTwits/yfinance/Groq/DuckDuckGo APIs (no
  `GROQ_API_KEY` available in this environment). Worth a full live run
  before considering Phase 0 fully closed out.
