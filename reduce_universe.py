import re

with open("config.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the large universe with a tiny one for testing
new_universe = 'STOCK_UNIVERSE = ["AAPL", "MSFT"]'
content = re.sub(r'STOCK_UNIVERSE\s*=\s*\[.*?\]', new_universe, content, flags=re.DOTALL)

with open("config.py", "w", encoding="utf-8") as f:
    f.write(content)
