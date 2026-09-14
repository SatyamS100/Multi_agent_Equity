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
   migrated to Groq (`langchain-groq`) via a find-and-replace script
   (`replace_claude.py`), landing on `llama-3.1-8b-instant`, which had
   *already* been swapped in once before this commit after an earlier Groq
   model deprecation. This left behind stale comments referring to Claude
   model tiers (Sonnet/Haiku/Opus) and one factual error (attributing
   "Constitutional AI" to Groq instead of Anthropic) — cleaned up in the
   Phase 0 pass below. `llama-3.1-8b-instant` itself was later removed from
   Groq's lineup entirely and had to be replaced again in Phase 3 — see
   below. Three Groq-model-deprecation incidents in this repo's history so
   far is why `config.GROQ_MODEL` exists as an env-overridable setting
   rather than a hardcoded string.

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

## Phase 2 — CI & the rule-ordering fix (this session, 2026-09-13)

Closed out two of Phase 1's "still open" items; the third
(`compute_composite_score()`'s dead fallback branch) remains open pending a
product decision on the confidence-weighting formula itself.

- Added `.github/workflows/tests.yml` — `pytest` now runs automatically on
  every push/PR to `main`, so the Phase 1 test suite actually enforces
  itself going forward instead of relying on someone remembering to run it.
- Fixed the `risk_classifier.apply_override_rules()` rule-ordering bug
  Phase 1 characterized: rule 1 (extreme volatility) is now a hard floor
  that returns immediately, so rule 4 (strong-fundamentals floor) can no
  longer silently lift a stock back out of `Speculative` right after rule 1
  put it there. This was judged safe to fix outright (rather than leaving
  it open like the composite-score item) because rule 1's own docstring
  already stated the volatility floor should apply "regardless of
  composite score" — the hard-floor behavior was the documented intent,
  not a new design decision.

Full before/after detail is in [BUGS.md](BUGS.md)'s Phase 2 table.

## Phase 3 — live verification (this session, 2026-09-13)

The user supplied a real `GROQ_API_KEY`, unblocking the one Phase 0-2 item
that needed one: an actual end-to-end run against live StockTwits,
yfinance, DuckDuckGo, and Groq. This phase was less about planned work and
more about what the live run immediately surfaced — a good reminder that
"tests pass" and "the real thing works" are different claims.

**Near-miss before any code changed:** the API key arrived pasted into
`.env.example` (a tracked file) instead of `.env` (gitignored). Caught via
`git diff` before staging anything — nothing was ever committed or pushed,
so no exposure occurred and no rotation was needed. Fixed by creating
`.env` with the real key and restoring `.env.example`'s placeholder. Take-
away: `.env.example` is a *template*, not a place to paste real secrets,
even temporarily.

**What the live run found** (full detail in [BUGS.md](BUGS.md)'s Phase 3
table):

1. StockTwits (Phase 0's header fix) and fundamentals both worked
   perfectly against live data — 24/24 and 23/24 tickers respectively (the
   one fundamentals miss, `SQ`, is genuinely delisted on Yahoo Finance, not
   a bug).
2. Reddit search crashed outright: `duckduckgo-search==6.3.7` picks a
   random browser-fingerprint preset per `DDGS()` call from a hardcoded
   list, and the `primp` version pip resolves today no longer supports
   several of those presets. Fixed by bumping to `duckduckgo-search==8.1.1`
   (which fixed this exact problem upstream).
3. Groq had deprecated `llama-3.1-8b-instant` — the *third* such incident
   in this repo's history (see the History section above). Every LLM call
   404'd; the pipeline degraded gracefully (as designed) but silently
   produced zero AI analysis for all 24 tickers while still reporting
   success. Fixed by querying Groq's live `/v1/models` endpoint, smoke-
   testing a candidate, and setting `openai/gpt-oss-20b` as the new
   `config.GROQ_MODEL` default.
4. With synthesis actually running, the evaluator (`evaluation_node`) was
   flagging 8-9 of every 10 tickers as "hallucinating" — its fact-check
   prompt was missing two fields (`composite_score`, `sector`) that the
   synthesis prompt *does* give the LLM and tells it to cite, so the
   evaluator had no way to verify claims it was never shown. Fixed by
   syncing the two prompts' data blocks; flag rate dropped to 6/10 with the
   remainder being more defensible edge cases (documented, not chased
   further).
5. `pytest` (bare invocation) had been silently importing and executing
   root-level `test_pipeline.py` — a manual script with unconditional
   module-level side effects — on every single run since Phase 1,
   **including in CI**, because the filename matches the default test
   discovery glob. This had been quietly inflating every "pytest run"
   timing since Phase 1; it only became obvious once a real API key made
   the accidental full pipeline run actually complete (200+ seconds)
   instead of erroring out early. Fixed with `pytest.ini`
   (`testpaths = tests`) — collection now takes ~4s, the suite runs in ~2s.
6. The `compute_composite_score()` product decision left open since Phase
   1 was resolved: keep `fundamental_confidence` hardcoded to `1.0`
   (trust fundamentals fully even with zero social signal). Docstring and
   test updated to state this is confirmed-intentional, not revisit-later.

**Verified, not just claimed:** re-ran the live pipeline after each fix
until it produced real, grounded LLM bull/bear cases, then drove the
actual running app (real `uvicorn` backend + static frontend, no mocks)
through a real browser click of "Run Pipeline" and confirmed the rendered
UI — sparklines, tier badges, LLM synthesis text — matched the API
response.

Full before/after detail is in [BUGS.md](BUGS.md)'s Phase 3 table.

## Phase 4 — dependency hygiene & universe fix (this session, 2026-09-13)

Closed the two concrete "Still open" items Phase 3 left behind — and, in
the process, a live run caught a third problem that a changelog/API-shape
check alone would have missed entirely.

- `duckduckgo-search` (deprecated upstream) replaced with the renamed
  `ddgs` package (`ddgs==9.16.0`). Confirmed live, before editing any code,
  that `DDGS().text(query, max_results=N)` returns the same `title`/`href`/
  `body` keys `search_reddit_agent.py` depends on — this was a same-API
  rename, not a version bump with behavior changes. The old package was
  uninstalled from the venv to prove the new one is fully self-sufficient.
- `SQ` in `config.STOCK_UNIVERSE` — delisted since Square Inc. renamed to
  Block, Inc. and moved to ticker `XYZ` in December 2021 — swapped for
  `XYZ`. Same company, so no universe-composition decision was needed;
  confirmed live via `yfinance.Ticker("XYZ")` that it resolves before
  wiring it into config.
- **The live run immediately failed** after those two changes landed: 16
  of 24 (67%) Reddit searches failed, tripping the fail-loud threshold.
  Root cause: `ddgs`'s default `backend="auto"` fans one `.text()` call out
  to ~8 engines in parallel (Google, Brave, Mojeek, Yahoo, Startpage,
  Wikipedia, Grokipedia, DuckDuckGo itself) instead of querying DuckDuckGo
  alone the way `duckduckgo-search` always did — across 24 tickers that's
  roughly 8x the request volume, and several of those engines 429/403
  almost immediately. Fixed by pinning `backend="duckduckgo"` explicitly in
  `search_reddit_agent.py`'s `.text()` call, restoring the original
  single-engine behavior. Re-ran live: failures dropped to 4/24 (17%,
  DuckDuckGo's own occasional soft-throttle, not a new problem), full
  pipeline completed with `Status: success`.

Verified, not just claimed: the pre-code-change API-shape check (same
result-dict keys) was necessary but not sufficient — it didn't cover a
changed *default parameter value*, which only a real 24-ticker end-to-end
run exposed. After the fix, `pytest` passed 64/64 with no new warnings, and
a full live `test_pipeline.py` run completed in 229.27s: `XYZ` fetched and
scored normally (StockTwits bullish, landed in the Conservative tier), 10
tickers got full LLM synthesis + evaluation, 14 got rule-based
classification, and risk-tier overrides fired as designed
(`PLTR`/`MSTR`/`RBLX` → Speculative on extreme volatility, `HOOD` →
Aggressive on contradictory sentiment). Full before/after detail in
[BUGS.md](BUGS.md)'s Phase 4 table.

Left open, deliberately not touched this phase: the evaluator's remaining
hallucination-flag false positives (needs fresh live-run evidence before
another prompt-tuning pass is justified, not a code fix — this run's
2 flags out of 10, on MSFT and JPM, are consistent with the previously
documented pattern) and GitHub branch-protection on `main` (a repo-settings
action outside what a commit can express — see BUGS.md's "Still open"
section).

## Phase 5 — Reddit-search reliability investigation (this session, 2026-09-13)

Planned to gather fresh live-run evidence on the evaluator hallucination-flag
rate — Phase 4's "still open" item. The first live run of this phase never
got that far: it aborted at the Reddit-search stage, surfacing a more urgent
regression than the one being investigated. This phase is a good example of
"tests pass" and "the real thing works" diverging again — the same lesson
Phase 3 learned, this time about an external dependency's behavior rather
than this repo's own code.

- Re-checked the Phase 4 branch-protection blocker first (cheap, no live
  pipeline needed): `gh api repos/{owner}/{repo} --jq .permissions` still
  returns `"admin": false` for this account. No change possible without
  repo-owner action; not re-attempted against the branch-protection endpoint
  itself since nothing upstream changed.
- Kicked off a live pipeline run to gather the evaluator evidence. It failed
  immediately: **Reddit search failed for 24/24 tickers (100%)**, a sharp
  jump from Phase 4's 4/24 (17%, attributed then to "DuckDuckGo's own
  occasional soft-throttle"). Investigated directly against `ddgs`, isolated
  from the rest of the pipeline, before touching any code:
  - A standalone call to `fetch_reddit_sentiment_via_search()` (no
    `ThreadPoolExecutor`, no concurrent StockTwits/fundamentals traffic)
    still failed 21/24 (88%) — ruling out concurrency as the cause.
  - Varying the delay between calls (1.5s → 5s) and constructing a fresh
    `DDGS()` instance per call instead of reusing one didn't reliably help —
    ruling out session-reuse and pacing as the cause.
  - Retrying the *identical* query up to 3 times with a 3-4s backoff
    recovered only 1 of 8 throttled tickers — meaning DuckDuckGo's
    `html.duckduckgo.com` endpoint (surfaced via an HTTP 202 response) is
    holding a sustained soft-block for tens of seconds at a time, not
    independently coin-flipping per request.
  - Conclusion: this is a real tightening of DuckDuckGo's anti-scraping
    posture since Phase 4 (same day), not a bug introduced by this repo's
    code, and not fixable by client-side request tuning alone.
- Added a bounded retry (`RETRY_ATTEMPTS = 3`, `RETRY_BACKOFF_SECONDS = 4`)
  around the search call in `search_reddit_agent.py` — standard resilience
  practice, harmless, and it did recover isolated cases during
  investigation. Re-ran the full live pipeline to verify: **23/24 (96%)
  still failed** — confirming the retry is not a fix for the underlying
  throttle, just a minor mitigation. Deliberately stopped here rather than
  escalating to proxy rotation, additional fingerprint/header spoofing, or
  CAPTCHA handling — those would cross from "resilience" into circumventing
  an anti-scraping control, out of scope regardless of the project's benign
  intent.

**Verified, not just claimed:** two independent full 24-ticker live runs
(before and after the retry change) both hit `raise_if_too_many_failed`'s
guard exactly as designed — it correctly aborted rather than silently
scoring on near-empty Reddit data. The root-cause investigation used direct,
isolated `ddgs` calls to rule out concurrency and query-syntax before
concluding the problem is upstream, rather than guessing from the pipeline's
aggregate error alone.

**Consequence for the original goal of this phase:** the evaluator
hallucination-flag evidence could not be gathered — the pipeline never
reaches `synthesis_node`/`evaluation_node` while Reddit-search aborts first.
That item remains open, now explicitly blocked on the Reddit-search issue
rather than just "needs a run." Full detail in [BUGS.md](BUGS.md)'s Phase 5
table and updated "Still open" section, which now includes an architectural
question for Phase 6: revert to the official (credentialed) Reddit API,
make Reddit-search failure degrade gracefully instead of hard-aborting the
pipeline, or accept the live-run flakiness as a known limitation of a
free/unauthenticated data source.

## Phase 6 — revert Reddit source to the official API (this session, 2026-09-14)

Phase 5 left a real architectural question open: DuckDuckGo's
anti-scraping defenses had tightened to the point of near-total live-run
failure for `search_reddit_agent.py` (100%, then 96%, of the universe
failing across two live runs), and three options were laid out rather than
picked unilaterally. The user chose explicitly: revert to the official,
credentialed Reddit API (PRAW) — the same trade the project's own history
made in reverse once already (see the History section above: PRAW → Reddit
dropped → DuckDuckGo search, specifically to avoid needing credentials).
That earlier tradeoff has now flipped back.

- Rewrote `search_reddit_agent.py` on `praw`, searching
  `r/wallstreetbets+stocks+investing` per ticker via `subreddit.search(...,
  time_filter="week")` instead of scraping DuckDuckGo. Added
  `get_reddit_client()` with the same fail-fast pattern as
  `graph.get_llm_client()` — raises a clear `RuntimeError` immediately if
  `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are unset, rather than failing
  deep in the fetch loop with an opaque `prawcore` auth error.
- Kept the `mention_momentum`/`spike_detected` formulas byte-for-byte
  identical in shape (`min(mentions_24h / 5.0, 1.0)`, spike at
  `mentions_24h >= 8`) — this is a data-source swap, not a scoring-formula
  change, consistent with CLAUDE.md's guidance to treat those as separate,
  deliberate decisions. `avg_post_score` and the 24h/7d mention split *did*
  get more accurate as a side effect: PRAW gives real post upvotes and real
  timestamps, which DuckDuckGo's scraped search results never had (the old
  code used a mocked constant and an unscoped-search-count heuristic to
  approximate them) — the same category of improvement as Phase 1 wiring in
  the previously-dead `price_chart` field, not a formula redesign.
- Dependency fallout, caught before it became a runtime surprise: adding
  `praw` force-upgrades `requests` (`prawcore` requires `>=2.34.2`, the repo
  had `2.32.4` pinned). Bumped the pin, then verified a *clean* venv
  install (not just `pip install` on top of the existing one) resolves with
  no conflicts and every top-level module still imports — the same
  clean-venv discipline CLAUDE.md calls out as necessary for
  `langgraph`/`langchain-*` bumps, applied here too since any pin change
  can ripple.

**Verified so far:** import check, `pytest` (64/64, no existing test
exercised this module directly), and the fail-fast credential check
(confirmed `get_reddit_client()` raises with `REDDIT_CLIENT_ID` unset) all
pass. **Not yet verified live** — this session had no real Reddit API
credentials available. Rather than claim the migration complete on unit
checks alone, it's tracked as the first "Still open" item in
[BUGS.md](BUGS.md) (issue #24), the same way Phase 0-2's GROQ-dependent
work stayed explicitly unverified-live until Phase 3 supplied a real key.
Needs `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` from a read-only "script"
app (https://www.reddit.com/prefs/apps) before a real `test_pipeline.py`
run can close it out — and, if that run completes, it would also finally
supply the fresh evaluator hallucination-flag evidence Phase 4-5 couldn't
gather.

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
  score, and — as of Phase 2 — no later rule can lift it back out) — these
  encode domain knowledge the raw composite score can't.
- `compute_composite_score()`'s `fundamental_confidence` is deliberately
  hardcoded to `1.0` — confirmed-intentional as of Phase 3, not something
  to "fix." Fundamentals are trusted fully even with zero social signal.
- `graph.py`'s `synthesis_node` (what data the LLM sees) and
  `evaluation_node` (what data the fact-checker sees) must stay in sync —
  see BUGS.md Phase 3 #16. If you add a field to one prompt's context
  block, add it to the other too, or the evaluator will flag correct
  claims as hallucinations.
