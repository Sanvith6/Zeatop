import asyncio
import time
from datetime import datetime, timezone
import httpx

# This script creates enough load to trigger a single incident.
# Threshold is 100 signals within 10 seconds.

API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}

async def get_token(client: httpx.AsyncClient) -> str:
    response = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
    response.raise_for_status()
    return response.json()["access_token"]

async def send_signal(client: httpx.AsyncClient, token: str, component_id: str):
    payload = {
        "component_id": component_id,
        "component_type": "api",
        "error_message": "Threshold test signal",
        "severity": "P1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await client.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})

async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("Authenticating...")
        token = await get_token(client)
        
        component_id = f"TEST_COMP_{int(time.time())}"
        print(f"Sending 120 signals for {component_id} to trigger incident...")
        
        tasks = []
        for _ in range(120):
            tasks.append(asyncio.create_task(send_signal(client, token, component_id)))
            await asyncio.sleep(0.01) # Spread slightly
            
        await asyncio.gather(*tasks)
        print(f"Successfully sent 120 signals. Check worker logs and dashboard for incident.")

if __name__ == "__main__":
    asyncio.run(main())
