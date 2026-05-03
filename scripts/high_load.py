import asyncio
import time
import httpx
from datetime import datetime, timezone

# Stress test to verify 10,000 signals/second ingestion capability.
# This script attempts to send a high volume of signals in a short burst.

API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}
TOTAL_SIGNALS = 10000  # Let's try 10000
CONCURRENCY = 200

async def get_token(client: httpx.AsyncClient) -> str:
    response = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
    response.raise_for_status()
    return response.json()["access_token"]

async def send_signal(client: httpx.AsyncClient, token: str, sem: asyncio.Semaphore):
    async with sem:
        payload = {
            "component_id": "STRESS_TEST_COMP",
            "component_type": "api",
            "error_message": "Stress test signal",
            "severity": "P2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await client.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
            return True
        except Exception:
            return False

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Authenticating...")
        token = await get_token(client)
        
        print(f"Starting stress test: {TOTAL_SIGNALS} signals with concurrency {CONCURRENCY}...")
        sem = asyncio.Semaphore(CONCURRENCY)
        start_time = time.perf_counter()
        
        tasks = [send_signal(client, token, sem) for _ in range(TOTAL_SIGNALS)]
        results = await asyncio.gather(*tasks)
        
        end_time = time.perf_counter()
        duration = end_time - start_time
        success_count = sum(1 for r in results if r)
        
        print(f"--- Stress Test Results ---")
        print(f"Total signals attempted: {TOTAL_SIGNALS}")
        print(f"Successful signals: {success_count}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Actual Throughput: {success_count / duration:.2f} signals/sec")
        print(f"Check /metrics or dashboard for system-wide stats.")

if __name__ == "__main__":
    asyncio.run(main())
