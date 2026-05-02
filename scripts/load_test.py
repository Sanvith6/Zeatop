import asyncio
import time
import httpx
import random
from datetime import datetime, timezone

# Configuration
API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}
CONCURRENCY = 10  # Number of parallel requests
TOTAL_REQUESTS = 1000

async def get_token(client: httpx.AsyncClient) -> str:
    response = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
    response.raise_for_status()
    return response.json()["access_token"]

async def send_signal(client: httpx.AsyncClient, token: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        component_id = random.choice(["DB_PRIMARY_01", "CACHE_01", "NET_GATEWAY", "AUTH_SVC"])
        payload = {
            "component_id": component_id,
            "component_type": "rdbms",
            "error_message": "Load test signal",
            "severity": "P2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await client.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"Error: {e}")

async def main():
    print(f"🚀 Starting load test: {TOTAL_REQUESTS} signals with concurrency {CONCURRENCY}...")
    start_time = time.perf_counter()
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        token = await get_token(client)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        
        tasks = [send_signal(client, token, semaphore) for _ in range(TOTAL_REQUESTS)]
        await asyncio.gather(*tasks)
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    print(f"✅ Finished! Sent {TOTAL_REQUESTS} signals in {duration:.2f} seconds.")
    print(f"📈 Average Rate: {TOTAL_REQUESTS / duration:.2f} signals/sec")

if __name__ == "__main__":
    asyncio.run(main())
