import re

with open('graph.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add Reddit text building logic
reddit_text_logic = """
            # Assemble Reddit posts as readable text
            reddit_text = "\\n".join([
                f"  [{p.get('subreddit','?')} | score:{p.get('score',0)}] "
                f"{p.get('title','')} - {p.get('text','')[:300]}"
                for p in t.get("top_reddit_posts", [])[:3]
            ]) or "  No Reddit posts available."
"""

content = content.replace('reddit_text = "None available"', reddit_text_logic.strip())

# Add Context variables back
context_str = """
Reddit Mention Momentum: {t['mention_momentum']} (range -1 to +1, positive = accelerating)
Reddit Spike Detected: {t['spike_detected']}
StockTwits Bull Ratio:
"""
content = content.replace("StockTwits Bull Ratio:\n", context_str)

reddit_posts_ctx = """
Reddit Posts (highest scored):
{reddit_text}

StockTwits Messages (most liked):
"""
content = content.replace("StockTwits Messages (most liked):", reddit_posts_ctx)

# Restore prompt
content = content.replace("You analyse StockTwits messages and", "You analyse Reddit discussions and StockTwits messages to")
content = content.replace("1. SARCASM AWARENESS: Retail boards use heavy irony.", "1. SARCASM AWARENESS: Reddit (especially r/wallstreetbets) uses heavy irony.")
content = content.replace("If posts are overwhelmingly positive", "If Reddit posts are overwhelmingly positive")

source_posts_logic = """
        source_posts = "\\n".join([
            f"- [{p.get('subreddit','?')}] {p.get('title','')} {p.get('text','')[:200]}"
            for p in ticker_data.get("top_reddit_posts", [])[:3]
        ])
"""
content = content.replace('source_posts = "" #', source_posts_logic.strip())

source_reddit_ctx = """
Reddit Posts:
{source_posts if source_posts else "None available"}

StockTwits Messages:
"""
content = content.replace("StockTwits Messages:", source_reddit_ctx)

with open('graph.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Restored graph.py")
