# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repo.

## What this repo is

See [README.md](README.md) for setup/architecture and
[CONTEXT.md](CONTEXT.md) for project history. [BUGS.md](BUGS.md) tracks
known issues — check it before assuming something is a fresh bug you found.

## Running things

```bash
pip install -r requirements.txt
# copy .env.example -> .env, set GROQ_API_KEY
uvicorn backend:app --reload --port 8000     # backend
python test_pipeline.py                       # direct smoke test, no HTTP, needs a real GROQ_API_KEY

pip install -r requirements-dev.txt
pytest                                         # unit + mocked-integration tests, no network, no key needed
```

Frontend is static (`frontend/index.html`, `script.js`, `style.css`) —
serve it with any static file server; it calls the backend at
`http://127.0.0.1:8000/api/run_pipeline`.

## Conventions

- **`config.py` is the single source of truth** for tunable constants
  (stock universe, scoring weights, risk thresholds, RSI/volatility
  windows). If you're tempted to hardcode a threshold in an agent file,
  it belongs in `config.py` instead.
- **One agent, one file, one responsibility**: `stocktwits_agent.py`,
  `search_reddit_agent.py`, `fundamentals.py` each fetch and normalize one
  data source and know nothing about the others. `sentiment_scorer.py` is
  the only place that fuses them. Don't reach across agents.
- **Comments describe the code as it exists, not as it once was or might
  become.** This codebase has a history of drifting (see CONTEXT.md) —
  migration scripts left in the tree, comments describing a UI framework
  that was swapped out months ago, an LLM provider that was replaced twice.
  When you change what a function does, update its docstring in the same
  edit — don't leave the next reader to find the mismatch.
- **"Interview: ..." blocks in docstrings are intentional** — this project
  doubles as interview prep for its author. Don't strip them; do fix them
  if they become factually wrong (e.g. referencing a model/library that's
  no longer used).
- **Fail loud on majority data-fetch failure.** All three data-fetch agents
  (`stocktwits_agent.py`, `fundamentals.py`, `search_reddit_agent.py`) call
  `data_fetch_utils.raise_if_too_many_failed(source, failed_tickers,
  universe_size)` at the end of their main orchestrator function. If a
  fourth data-fetch agent is ever added, it should call this too rather
  than inventing its own threshold/exception — keeps the failure message
  format and the 50% threshold consistent everywhere.
- **`requirements.txt` is pinned.** If you add or bump a dependency, pin
  the exact version and verify it installs *and imports* cleanly
  (`python -c "import <module>"` for every top-level module, not just the
  one you touched — `langgraph`/`langchain-core`/`langchain-groq` version
  triples are especially prone to resolver conflicts with each other).

## Known sharp edges

- **StockTwits blocks requests without a browser-like `User-Agent`.** If
  StockTwits fetches start silently failing again, check
  `stocktwits_agent.REQUEST_HEADERS` first before assuming it's a rate
  limit or API change.
- **Groq deprecates model names without much notice** — three times in this
  repo's history now (see CONTEXT.md), most recently `llama-3.1-8b-instant`
  itself, replaced with `openai/gpt-oss-20b` in Phase 3. The model id is
  `config.GROQ_MODEL` (env-overridable via `GROQ_MODEL` in `.env`). If
  synthesis/evaluation start 404ing with `model_not_found`, don't guess a
  replacement — query `GET https://api.groq.com/openai/v1/models` with
  `Authorization: Bearer $GROQ_API_KEY` to list currently-valid ids, and
  smoke-test a candidate with a real `.invoke()` call before committing to
  it as the new default. `get_llm_client()` also raises immediately if
  `GROQ_API_KEY` is unset, rather than failing deep inside a node — if you
  add a new entry point that calls it, don't swallow that exception
  silently.
- **`graph.py`'s synthesis and evaluation prompts must stay in sync.**
  `synthesis_node`'s `ticker_contexts` block is what data the LLM is told
  it may cite; `evaluation_node`'s "Quantitative Data Available" block is
  what the fact-checker is allowed to verify claims against. A Phase 3 live
  run found these had drifted (evaluator missing `composite_score` and
  `sector`), causing the evaluator to flag correct, data-grounded claims as
  hallucinations on 8-9 of 10 tickers per run — not occasional noise, a
  systematic false-positive rate. If you add a field to one prompt's
  context, add it to the other, or run a live test to check for a spike in
  `hallucination_flag: true` results.
- **`duckduckgo-search` (imported as `duckduckgo_search`, used by
  `search_reddit_agent.py`) is pinned to `8.1.1`, not the latest.** 6.3.7
  crashed intermittently (`primp.BuilderError: Invalid impersonate:
  "chrome_100"`) because it randomly picks a browser-fingerprint preset per
  `DDGS()` call from a hardcoded list that goes stale as `primp` evolves;
  8.1.1 fixed this upstream. The package is itself deprecated in favor of a
  renamed `ddgs` package (emits a `RuntimeWarning` on every call) — that
  migration is documented as future work in BUGS.md, not done yet.
- **`pytest` (bare invocation) only discovers `tests/`** — see
  `pytest.ini`. Root-level `test_pipeline.py` matches pytest's default
  `test_*.py` glob but has unconditional module-level side effects (runs
  the real pipeline at import time); without the `testpaths` restriction,
  every `pytest` run silently executed a real, partial pipeline run before
  collection even finished — this happened undetected from Phase 1 through
  Phase 2, including in CI. Don't add new root-level `test_*.py`/`*_test.py`
  files expecting them to be picked up automatically; put tests in
  `tests/`, or if a script genuinely needs a name matching that glob,
  double-check `pytest --collect-only` doesn't sweep it in.
- **CORS is an explicit origin allowlist** (`config.CORS_ORIGINS`, env var
  `CORS_ORIGINS`), not `"*"`. If the frontend can't reach the backend from
  a new dev-server port, add that origin rather than widening to `"*"` —
  widening it back would reintroduce the `allow_credentials`/wildcard
  conflict this was fixed for (see BUGS.md #6).
- **Only the top 10 tickers (`TOP_N_FOR_LLM`) get LLM synthesis.** The rest
  get rule-based risk classification only (`has_llm_analysis: False`).
  This is by design (cost/latency control), not a bug — don't "fix" it by
  running LLM synthesis on the full universe without discussing the cost
  tradeoff first.
- **`risk_classifier.apply_override_rules()`'s rule 1 (extreme volatility)
  is a hard floor that returns immediately** — rules 2-5 never run once
  rule 1 fires. This was a deliberate Phase 2 fix (see BUGS.md #13): rule 4
  used to be able to silently lift a stock back out of Speculative right
  after rule 1 put it there. If you add a rule 6+, decide explicitly
  whether it should also be able to override rule 1's floor, and don't
  assume the current fall-through ordering of rules 2-5 is load-bearing —
  it isn't, by design.
- **`sentiment_scorer.compute_composite_score()`'s `fundamental_confidence`
  is hardcoded to `1.0`** — confirmed intentional as of Phase 3 (see
  BUGS.md), not a latent bug. It means the composite score can never
  actually be "no data at all → 50.0" through the normal call path; when
  social confidence is 0, the composite deliberately collapses to exactly
  the fundamental score instead. If you want to change this, it's a
  scoring-formula change affecting every ticker — treat it as a product
  decision, not a drive-by fix.
- **`.env.example` is a template, never a place for a real value.** A real
  `GROQ_API_KEY` ended up there once (Phase 3) instead of in `.env` — one
  file-name mix-up away from pushing a live credential, caught before any
  commit. `.env.example` is tracked by git; `.env` is gitignored. If you
  ever see a non-empty secret in `.env.example`, stop and fix it before
  doing anything else — don't commit past it.

## Before considering a change done

- Run `python -c "import backend"` (imports every module transitively) to
  catch import-time errors before they hit runtime.
- Run `pytest` (needs `requirements-dev.txt` installed). It's fast and
  needs no network/API key — no excuse to skip it before committing.
  `.github/workflows/tests.yml` runs the same thing on every push/PR to
  `main`, so a broken test surfaces on GitHub even if you forget locally.
- If you touched `requirements.txt`, install into a clean venv and re-run
  the import check — don't just trust that a version bump "should" work.
- If you touched frontend rendering of any server-derived text (ticker
  data, LLM output), make sure it goes through `escapeHtml()` in
  `script.js` before landing in `innerHTML`. Numeric values computed
  client-side (like the sparkline's SVG coordinates) don't need escaping —
  only strings that originate from the server/LLM do.
- If you touched a pure function covered by `tests/`, update the test in
  the same change — don't leave it asserting the old behavior.
- If `pytest` (no args) suddenly takes way longer than ~2-3 seconds or
  spits out a `duckduckgo_search`/`primp` warning, something is importing
  `test_pipeline.py` again — check `pytest.ini`'s `testpaths` is still in
  effect before assuming it's a real regression.
