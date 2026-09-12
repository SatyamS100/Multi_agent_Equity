import time
from fastapi import HTTPException
from backend import run_pipeline

start_time = time.time()
print("Starting parallel pipeline...")
try:
    result = run_pipeline()
except HTTPException as e:
    print(f"\nPipeline finished in {time.time() - start_time:.2f} seconds.")
    print(f"Status: error")
    print(f"Error Message: {e.detail}")
else:
    print(f"\nPipeline finished in {time.time() - start_time:.2f} seconds.")
    print(f"Status: {result.get('status')}")
    print(f"Number of tickers classified: {sum(len(v) for v in result.get('classified', {}).values())}")
