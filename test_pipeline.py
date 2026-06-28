import time
from backend import run_pipeline

start_time = time.time()
print("Starting parallel pipeline...")
result = run_pipeline()
end_time = time.time()

duration = end_time - start_time
print(f"\nPipeline finished in {duration:.2f} seconds.")
print(f"Status: {result.get('status')}")
if result.get('status') == 'error':
    print(f"Error Message: {result.get('message')}")
else:
    print(f"Number of tickers classified: {sum(len(v) for v in result.get('classified', {}).values())}")
