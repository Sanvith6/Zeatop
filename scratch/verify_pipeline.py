import asyncio
import httpx
from datetime import datetime, timezone

API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Authenticating...")
        try:
            resp = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
            resp.raise_for_status()
            token = resp.json()["access_token"]
        except Exception as e:
            print(f"Auth failed: {e}")
            return

        print("Sending 50 test signals...")
        for i in range(50):
            payload = {
                "component_id": f"TEST_COMPONENT_{i%5}",
                "component_type": "compute",
                "error_message": f"Test signal {i}",
                "severity": "P2" if i % 10 != 0 else "P0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await client.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
            if i % 10 == 0:
                print(f"Sent {i} signals...")
        
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
