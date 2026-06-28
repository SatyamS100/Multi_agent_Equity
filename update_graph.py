import re

with open('graph.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove Reddit posts building
content = re.sub(
    r'# Assemble Reddit posts as readable text.*?or "  No Reddit posts available\."',
    'reddit_text = "None available"', 
    content, flags=re.DOTALL
)

# Remove Reddit context variables
content = re.sub(
    r'Reddit Mention Momentum:.*?\n',
    '',
    content
)
content = re.sub(
    r'Reddit Spike Detected:.*?\n',
    '',
    content
)
content = re.sub(
    r'Reddit Posts \(highest scored\):\n\{reddit_text\}\n\n',
    '',
    content
)

# Fix prompts
content = content.replace("alternative data and social sentiment signals. You analyse Reddit discussions and", "alternative data and social sentiment signals. You analyse StockTwits messages and")
content = content.replace("1. SARCASM AWARENESS: Reddit (especially r/wallstreetbets) uses heavy irony.", "1. SARCASM AWARENESS: Retail boards use heavy irony.")
content = content.replace("If Reddit posts are overwhelmingly positive", "If posts are overwhelmingly positive")
content = content.replace("Reddit Posts:\n{source_posts if source_posts else \"None available\"}\n\n", "")
content = content.replace("source_posts = \"\\n\".join([", "source_posts = \"\" #")
content = content.replace("f\"- [{p.get('subreddit','?')}] {p.get('title','')} {p.get('text','')[:200]}\"", "")
content = content.replace("for p in ticker_data.get(\"top_reddit_posts\", [])[:3]", "")

with open('graph.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated graph.py")
