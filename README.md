# Multi-Agent Equity Sentiment Platform

Fuses social sentiment (StockTwits, Reddit-via-search), quantitative
fundamentals (yfinance), and LLM synthesis (Groq + LangGraph) into a ranked,
risk-classified view of a 24-stock universe. FastAPI backend, vanilla JS
frontend.

See [CONTEXT.md](CONTEXT.md) for project history and why things are built
this way, and [BUGS.md](BUGS.md) for known issues and what's still missing.

## Architecture

```
                ┌─────────────────┐
                │   config.py      │  STOCK_UNIVERSE, weights, thresholds
                └────────┬─────────┘
                         │
   ┌─────────────────────┼─────────────────────┐
   ▼                     ▼                     ▼
stocktwits_agent.py  search_reddit_agent.py  fundamentals.py
(StockTwits API,     (Reddit posts via       (yfinance: price,
 labeled sentiment)   DuckDuckGo search)       RSI, volatility, P/E...)
   │                     │                     │
   └─────────────────────┼─────────────────────┘
                         ▼
                sentiment_scorer.py   → confidence-weighted composite score
                         │
                         ▼
                  graph.py (LangGraph) → LLM synthesis + LLM-as-judge
                         │              evaluation, top 10 tickers only
                         ▼
                risk_classifier.py     → tier assignment + overrides
                         │
                         ▼
                    backend.py         → FastAPI, GET /api/run_pipeline
                         │
                         ▼
                frontend/ (vanilla JS) → renders ranked, tiered ticker cards
```

`stocktwits_agent.py`, `search_reddit_agent.py`, and `fundamentals.py` all
share `data_fetch_utils.py`'s fail-loud guard: if more than half the
universe fails to fetch, the agent raises instead of silently handing the
scorer placeholder/neutral data (see [BUGS.md](BUGS.md) #2, #8).

## Setup

1. **Python 3.12+** and a virtualenv:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   ```

2. **Environment variables** — copy `.env.example` to `.env` and fill in:
   - `GROQ_API_KEY` — required, get one at https://console.groq.com/keys
   - `GROQ_MODEL` — optional, defaults to `llama-3.1-8b-instant`. Override
     if Groq deprecates the default (see
     [CLAUDE.md](CLAUDE.md#known-sharp-edges))
   - `CORS_ORIGINS` — optional, comma-separated list of frontend origins
     allowed to call the API (defaults to `http://localhost:5500,http://127.0.0.1:5500`)

3. **Run the backend**:
   ```bash
   uvicorn backend:app --reload --port 8000
   ```

4. **Open the frontend** — serve `frontend/` with any static file server
   (e.g. VS Code Live Server on port 5500) and open `index.html`. Opening the
   file directly (`file://`) will not satisfy the CORS origin allowlist.

5. Click **Run Pipeline**. A full run takes roughly 20-40 seconds (StockTwits,
   Reddit search, and fundamentals fetch in parallel; LLM synthesis runs on
   the top 10 tickers only).

## Tests

Unit tests + a mocked backend integration test — no live network calls, no
`GROQ_API_KEY` needed:

```bash
pip install -r requirements-dev.txt
pytest
```

Covers the pure scoring/classification/fundamentals functions
(`sentiment_scorer.py`, `risk_classifier.py`, `fundamentals.py`), the
shared fail-loud guard (`data_fetch_utils.py`), and `backend.py`'s
success/failure/CORS behavior via FastAPI's `TestClient`, with the three
data-fetch agents and `run_sentiment_graph` monkeypatched out.

`test_pipeline.py` is a separate, manual, network-dependent smoke test that
runs the real pipeline end-to-end (hits live StockTwits/yfinance/
DuckDuckGo/Groq APIs — needs a real `GROQ_API_KEY`):

```bash
python test_pipeline.py
```

## Known limitations

Tracked in [BUGS.md](BUGS.md). Headline items: nothing has exercised the
real external APIs end-to-end yet in this environment (no `GROQ_API_KEY`
available), no CI runs `pytest` automatically on push, and two
characterized-but-unfixed quirks in the override-rule/composite-score logic
need a product decision before they're worth changing.
