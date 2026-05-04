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
    tasks: list[asyncio.Task[None]] = []
    for index in range(1, count + 1):
        tasks.append(asyncio.create_task(send_signal(client, token, component_id, component_type, severity, message)))
        if index % 10 == 0 or index == count:
            print(f"{component_id}: sent {index}/{count}")
        await asyncio.sleep(delay)
    await asyncio.gather(*tasks)


async def send_random_noise(client: httpx.AsyncClient, token: str) -> None:
    components = [
        ("CACHE_CLUSTER_01", "cache"),
        ("CACHE_CLUSTER_02", "cache"),
        ("QUEUE_INGEST_01", "queue"),
        ("QUEUE_EVENTS_02", "queue"),
    ]
    for index in range(1, 31):
        component_id, component_type = random.choice(components)
        severity = random.choice(["P2", "P3"])
        await send_signal(client, token, component_id, component_type, severity, "Intermittent degraded performance")
        print(f"noise: sent {index}/30")
        await asyncio.sleep(0.1)


async def main() -> None:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = await get_token(client)
        print("Starting RDBMS outage simulation")
        await send_burst(client, token, 150, 8, "DB_PRIMARY_01", "rdbms", "P0", "Primary database connection timeout")
        print("Starting MCP failure simulation")
        await send_burst(client, token, 80, 5, "MCP_HOST_02", "mcp", "P0", "MCP control plane unreachable")
        print("Sending random lower-severity signals")
        await send_random_noise(client, token)
    print("Simulation complete")


if __name__ == "__main__":
    asyncio.run(main())
