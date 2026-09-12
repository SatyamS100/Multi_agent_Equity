import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import concurrent.futures

from stocktwits_agent import fetch_all_stocktwits
from fundamentals import fetch_all_fundamentals
from search_reddit_agent import fetch_reddit_sentiment_via_search
from sentiment_scorer import score_all_tickers, get_trending_now
from graph import run_sentiment_graph
from risk_classifier import classify_all_tickers
from config import STOCK_UNIVERSE, CORS_ORIGINS

logger = logging.getLogger(__name__)

app = FastAPI()

# allow_credentials=True cannot be combined with a wildcard origin (browsers
# reject it, and it's a bad idea anyway). The frontend doesn't send cookies,
# so we keep credentials off and restrict to an explicit origin allowlist.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/api/run_pipeline")
def run_pipeline():
    universe_list = STOCK_UNIVERSE
    try:
        # Phase 1: Parallel Data Ingestion
        # Using ThreadPoolExecutor to drastically cut runtime from 90s to 30s
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_reddit = executor.submit(fetch_reddit_sentiment_via_search, universe_list)
            future_st     = executor.submit(fetch_all_stocktwits, universe_list)
            future_fund   = executor.submit(fetch_all_fundamentals, universe_list)

            reddit_data = future_reddit.result()
            st_data     = future_st.result()
            fund_data   = future_fund.result()

        # Phase 2: Scoring & Fusion
        scored = score_all_tickers(reddit_data, st_data, fund_data, universe_list)

        # Phase 3: Trending Spotlight
        trending = get_trending_now(scored, n=3)

        # Phase 4: LLM Synthesis (on top N only)
        final_reports = run_sentiment_graph(scored)

        # Phase 5: Risk Classification
        classified = classify_all_tickers(final_reports)

        return {
            "status": "success",
            "classified": classified,
            "trending": trending,
            "scored_flat": scored,
            "run_time": datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        # Upstream data-source failure (StockTwits blocked, yfinance down,
        # Groq error, etc). Surface it as a real error status instead of a
        # 200 with a status:"error" body the frontend has to know to check.
        logger.exception("Pipeline run failed")
        raise HTTPException(status_code=502, detail=str(e))
