import re

with open("config.py", "r", encoding="utf-8") as f:
    content = f.read()

new_universe = """STOCK_UNIVERSE = [
    # Mega-cap Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", 
    # High Beta / Retail Darlings
    "PLTR", "COIN", "SHOP", "SQ", "GME", "AMC",
    # Value / Dividend
    "JPM", "XOM", "PFE", "DIS",
    # Speculative / Growth
    "SOFI", "RIVN", "RBLX", "SNAP", "HOOD"
]"""

content = re.sub(r'STOCK_UNIVERSE\s*=\s*\[.*?\]', new_universe, content, flags=re.DOTALL)

with open("config.py", "w", encoding="utf-8") as f:
    f.write(content)
