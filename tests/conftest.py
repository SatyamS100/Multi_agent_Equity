import os
import sys

# tests/ has no __init__.py, so pytest's default import mode only puts
# tests/ itself on sys.path. The project modules (config.py, graph.py, ...)
# live one directory up, at the repo root — add it explicitly so
# `import sentiment_scorer` etc. work regardless of where pytest is invoked
# from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
