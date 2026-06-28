from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from stocktwits_agent import fetch_all_stocktwits
from fundamentals import fetch_all_fundamentals
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
        # We removed Reddit as the API went paid and user opted for a single source
        reddit_data = {} 
        
        # 1. Fetch StockTwits
        st_data = fetch_all_stocktwits(universe_list)
        
        # 2. Fetch Fundamentals
        fund_data = fetch_all_fundamentals(universe_list)
        
        # 3. Score
        scored = score_all_tickers(reddit_data, st_data, fund_data, universe_list)
        
        # 4. Trending
        trending = get_trending_now(scored, n=3)
        
        # 5. LLM Synthesis
        final_reports = run_sentiment_graph(scored)
        
        # 6. Risk Classification
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
