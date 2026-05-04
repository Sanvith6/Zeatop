import asyncio
import random
from datetime import datetime, timezone

import httpx

API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}


async def get_token(client: httpx.AsyncClient) -> str:
    response = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
    response.raise_for_status()
    return response.json()["access_token"]


async def send_signal(
    client: httpx.AsyncClient,
    token: str,
    component_id: str,
    component_type: str,
    severity: str,
    message: str,
) -> None:
    payload = {
        "component_id": component_id,
        "component_type": component_type,
        "error_message": message,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    response = await client.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()


async def send_burst(
    client: httpx.AsyncClient,
    token: str,
    count: int,
    duration_seconds: float,
    component_id: str,
    component_type: str,
    severity: str,
    message: str,
) -> None:
    delay = duration_seconds / count
    tasks = []
    for index in range(1, count + 1):
        tasks.append(asyncio.create_task(send_signal(client, token, component_id, component_type, severity, message)))
        if index % 10 == 0 or index == count:
            print(f"{component_id}: sent {index}/{count}")
        await asyncio.sleep(delay)
    await asyncio.gather(*tasks)


async def main() -> None:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = await get_token(client)
        
        print("Starting External Dependency Failure Simulation")
        print("Scenario: Stripe API Gateway is returning 503 Service Unavailable")
        await send_burst(
            client, token, 120, 6, 
            "PAYMENT_GATEWAY_01", "external", "P1", 
            "Stripe API Error: 503 Service Unavailable"
        )
        
        print("\nStarting API Gateway Timeout Simulation")
        print("Scenario: Nginx configuration error causing 504 Gateway Timeouts")
        await send_burst(
            client, token, 60, 4, 
            "API_GATEWAY_PROD", "compute", "P0", 
            "Upstream connection timeout (504 Gateway Timeout)"
        )
        
    print("\nSimulation 2 complete")


if __name__ == "__main__":
    asyncio.run(main())
