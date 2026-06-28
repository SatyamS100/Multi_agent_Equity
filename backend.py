from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import concurrent.futures

from stocktwits_agent import fetch_all_stocktwits
from fundamentals import fetch_all_fundamentals
from search_reddit_agent import fetch_reddit_sentiment_via_search
from sentiment_scorer import score_all_tickers, get_trending_now
from graph import run_sentiment_graph
from risk_classifier import classify_all_tickers
from config import STOCK_UNIVERSE

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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
        return {"status": "error", "message": str(e)}
