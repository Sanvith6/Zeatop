import asyncio
import time
import aiohttp
import sys
from datetime import datetime, timezone

# Configuration
API_URL = "http://localhost:8000/api/signals"
AUTH_URL = "http://localhost:8000/api/auth/token"
USERNAME = "sre-intern"
PASSWORD = "zeotap-local"
CONCURRENT_WORKERS = 500
DURATION_SECONDS = 10

async def get_token():
    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, json={"username": USERNAME, "password": PASSWORD}) as resp:
            data = await resp.json()
            return data["access_token"]

async def worker(worker_id, token, stats):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "component_id": f"LOAD_TEST_{worker_id}",
        "component_type": "compute",
        "severity": "P1",
        "error_message": f"High load simulation from worker {worker_id}",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    end_time = time.time() + DURATION_SECONDS
    async with aiohttp.ClientSession(headers=headers) as session:
        while time.time() < end_time:
            try:
                start_req = time.time()
                async with session.post(API_URL, json=payload) as resp:
                    if resp.status == 202:
                        stats["success"] += 1
                    else:
                        stats["error"] += 1
                        stats["last_error"] = await resp.text()
                stats["latencies"].append(time.time() - start_req)
            except Exception as e:
                stats["error"] += 1
                stats["last_error"] = str(e)
            
            # Small yield to prevent CPU pinning if needed, 
            # but we want "tight loop" as requested.
            # asyncio.sleep(0) is better than nothing for context switching.
            await asyncio.sleep(0)

async def main():
    print(f"--- Starting Load Test ---")
    print(f"Workers: {CONCURRENT_WORKERS}")
    print(f"Duration: {DURATION_SECONDS}s")
    
    try:
        token = await get_token()
    except Exception as e:
        print(f"Failed to get auth token: {e}")
        return

    stats = {"success": 0, "error": 0, "latencies": [], "last_error": ""}
    
    start_time = time.time()
    workers = [worker(i, token, stats) for i in range(CONCURRENT_WORKERS)]
    await asyncio.gather(*workers)
    total_time = time.time() - start_time
    
    avg_throughput = stats["success"] / total_time
    error_rate = (stats["error"] / (stats["success"] + stats["error"])) * 100 if (stats["success"] + stats["error"]) > 0 else 0
    
    avg_latency = (sum(stats["latencies"]) / len(stats["latencies"])) * 1000 if stats["latencies"] else 0
    p99_latency = sorted(stats["latencies"])[int(len(stats["latencies"]) * 0.99)] * 1000 if stats["latencies"] else 0

    print(f"\n--- Final Report ---")
    print(f"Total Requests: {stats['success'] + stats['error']}")
    print(f"Successful: {stats['success']}")
    print(f"Errors: {stats['error']}")
    print(f"Error Rate: {error_rate:.2f}%")
    print(f"Actual Throughput: {avg_throughput:.2f} req/s")
    print(f"Avg Latency: {avg_latency:.2f} ms")
    print(f"p99 Latency: {p99_latency:.2f} ms")
    
    if stats["last_error"]:
        print(f"Last Error: {stats['last_error']}")

if __name__ == "__main__":
    asyncio.run(main())
