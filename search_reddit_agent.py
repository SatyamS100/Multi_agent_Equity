import logging
import time
from duckduckgo_search import DDGS
from collections import defaultdict
from typing import Dict, List
import re

from config import STOCK_UNIVERSE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_reddit_sentiment_via_search(universe: List[str] = STOCK_UNIVERSE) -> Dict[str, dict]:
    """
    Simulates the Reddit API by using DuckDuckGo to search public Reddit forums.
    This extracts recent discussions without needing a paid API key.
    """
    results = {}
    ddgs = DDGS()
    
    for ticker in universe:
        logger.info(f"Searching Reddit for {ticker} via DDG...")
        
        # Build search query targeting r/wallstreetbets and r/stocks
        query = f'"{ticker}" stock site:reddit.com/r/wallstreetbets OR site:reddit.com/r/stocks'
        
        posts = []
        try:
            # Fetch up to 10 recent results
            search_results = list(ddgs.text(query, max_results=10))
            
            for item in search_results:
                posts.append({
                    "title": item.get("title", ""),
                    "text": item.get("body", ""),
                    "url": item.get("href", ""),
                    "score": 100, # Mock score since search engines don't provide upvotes
                    "subreddit": "wallstreetbets" if "wallstreetbets" in item.get("href", "") else "stocks"
                })
        except Exception as e:
            logger.error(f"Search failed for {ticker}: {e}")
            
        # Simulate the structured output expected by sentiment_scorer
        mentions = len(posts)
        
        # Simulate momentum based on search result density
        momentum = min(mentions / 5.0, 1.0)
        spike = mentions >= 8
        
        results[ticker] = {
            "ticker":              ticker,
            "total_mentions":      mentions,
            "mentions_24h":        mentions,
            "mentions_7d":         mentions * 3,
            "spike_detected":      spike,
            "mention_momentum":    round(momentum, 2),
            "avg_post_score":      100.0,
            "top_posts":           posts[:5],
            "subreddit_breakdown": {"wallstreetbets": mentions, "stocks": 0, "investing": 0},
        }
        
        # Polite delay to prevent rate limits from DDG
        time.sleep(1.5)
        
    return results
