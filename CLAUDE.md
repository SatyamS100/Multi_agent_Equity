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
- **Groq deprecates model names without much notice** — this has already
  broken the pipeline once (see CONTEXT.md). The model id is
  `config.GROQ_MODEL` (env-overridable via `GROQ_MODEL` in `.env`, defaults
  to `llama-3.1-8b-instant`), read by `graph.py:get_llm_client()`. If
  synthesis/evaluation start failing with an API error mentioning the
  model, set `GROQ_MODEL` in `.env` rather than editing `graph.py` — check
  https://console.groq.com/docs/models for current valid ids.
  `get_llm_client()` also raises immediately if `GROQ_API_KEY` is unset,
  rather than failing deep inside a node — if you add a new entry point
  that calls it, don't swallow that exception silently.
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
- **`risk_classifier.apply_override_rules()`'s five rules run in a fixed
  sequence and can interact** — e.g. rule 4 (strong-fundamentals floor) can
  immediately undo rule 1 (extreme-volatility floor) if a stock has both
  extreme volatility and fundamental_score > 80. This is characterized in
  `tests/test_risk_classifier.py` and BUGS.md, not fixed — the correct
  behavior is a product decision (should rule 1 be a hard floor?), so don't
  "fix" it silently as a drive-by change.
- **`sentiment_scorer.compute_composite_score()`'s `fundamental_confidence`
  is hardcoded to `1.0`**, which means the composite score can never
  actually be "no data at all → 50.0" through the normal call path — see
  BUGS.md. If you touch this function's confidence weighting, re-read that
  entry first.

## Before considering a change done

- Run `python -c "import backend"` (imports every module transitively) to
  catch import-time errors before they hit runtime.
- Run `pytest` (needs `requirements-dev.txt` installed). It's fast and
  needs no network/API key — no excuse to skip it before committing.
- If you touched `requirements.txt`, install into a clean venv and re-run
  the import check — don't just trust that a version bump "should" work.
- If you touched frontend rendering of any server-derived text (ticker
  data, LLM output), make sure it goes through `escapeHtml()` in
  `script.js` before landing in `innerHTML`. Numeric values computed
  client-side (like the sparkline's SVG coordinates) don't need escaping —
  only strings that originate from the server/LLM do.
- If you touched a pure function covered by `tests/`, update the test in
  the same change — don't leave it asserting the old behavior.
