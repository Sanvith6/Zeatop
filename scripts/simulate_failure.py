import asyncio
import random
import sys
from datetime import datetime, timezone

import httpx

API_URL = "http://localhost:8000/api/signals"
TOKEN_URL = "http://localhost:8000/api/auth/token"
DEMO_CREDENTIALS = {"username": "sre-intern", "password": "zeotap-local"}


async def get_token(client: httpx.AsyncClient) -> str:
    try:
        response = await client.post(TOKEN_URL, json=DEMO_CREDENTIALS)
        response.raise_for_status()
        return response.json()["access_token"]
    except Exception as e:
        print(f"Failed to get auth token: {e}")
        sys.exit(1)


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
            print(f"[{component_id}] sent {index}/{count}")
        await asyncio.sleep(delay)
    await asyncio.gather(*tasks)


async def run_scenario_1(client: httpx.AsyncClient, token: str):
    """Infrastructure Failures (RDBMS & MCP)"""
    print("\n--- Scenario 1: Infrastructure Outages ---")
    print("Simulating RDBMS connection timeouts...")
    await send_burst(client, token, 150, 5, "DB_PRIMARY_01", "rdbms", "P0", "Primary database connection timeout")
    print("Simulating MCP control plane failure...")
    await send_burst(client, token, 80, 4, "MCP_HOST_02", "mcp", "P0", "MCP control plane unreachable")


async def run_scenario_2(client: httpx.AsyncClient, token: str):
    """External Dependency Failures (Stripe & API Gateway)"""
    print("\n--- Scenario 2: External Dependencies ---")
    print("Simulating Stripe API 503s...")
    await send_burst(client, token, 120, 5, "PAYMENT_GATEWAY_01", "external", "P1", "Stripe API Error: 503 Service Unavailable")
    print("Simulating API Gateway 504 timeouts...")
    await send_burst(client, token, 60, 3, "API_GATEWAY_PROD", "compute", "P0", "Upstream connection timeout (504 Gateway Timeout)")


async def run_scenario_3(client: httpx.AsyncClient, token: str):
    """Resource Exhaustion (Cache OOM & Disk Latency)"""
    print("\n--- Scenario 3: Resource Exhaustion ---")
    print("Simulating Redis Memory Leak...")
    await send_burst(client, token, 200, 8, "CACHE_CLUSTER_01", "cache", "P2", "Redis OOM: Out of memory, eviction policy failed")
    print("Simulating High Disk Latency...")
    await send_burst(client, token, 90, 4, "STORAGE_NODE_05", "storage", "P1", "Disk I/O Latency > 500ms (High Wait State)")


async def main() -> None:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = await get_token(client)
        
        # If no arguments, run all. Otherwise run specific scenario.
        args = sys.argv[1:]
        if not args or "all" in args:
            await run_scenario_1(client, token)
            await run_scenario_2(client, token)
            await run_scenario_3(client, token)
        else:
            if "1" in args: await run_scenario_1(client, token)
            if "2" in args: await run_scenario_2(client, token)
            if "3" in args: await run_scenario_3(client, token)

    print("\nAll requested simulations complete.")


if __name__ == "__main__":
    asyncio.run(main())
