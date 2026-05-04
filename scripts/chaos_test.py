import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# Configuration
API_URL = "http://localhost:8000/api/signals"
AUTH_URL = "http://localhost:8000/api/auth/token"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "ims"
COLLECTION_NAME = "signals"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chaos-test")

async def get_token():
    async with httpx.AsyncClient() as client:
        resp = await client.post(AUTH_URL, json={"username": "sre-intern", "password": "zeotap-local"})
        resp.raise_for_status()
        return resp.json()["access_token"]

async def send_signals(count: int, start_idx: int, token: str):
    logger.info(f"Sending {count} signals starting from index {start_idx}...")
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}"}
        for i in range(count):
            payload = {
                "component_id": f"CHAOS_NODE_{i + start_idx}",
                "component_type": "api",
                "error_message": f"Chaos test signal {i + start_idx}",
                "severity": "P2",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            try:
                await client.post(API_URL, json=payload, headers=headers)
                if (i + 1) % 100 == 0:
                    logger.info(f"Sent {i + 1}/{count} signals")
            except Exception as e:
                logger.error(f"Failed to send signal {i + start_idx}: {e}")

async def get_mongo_count():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    count = await db[COLLECTION_NAME].count_documents({})
    client.close()
    return count

def run_command(cmd_list):
    logger.info(f"Running command: {' '.join(cmd_list)}")
    subprocess.run(cmd_list, check=True)

async def main():
    token = await get_token()
    
    logger.info("--- STARTING CHAOS TEST ---")
    initial_count = await get_mongo_count()
    logger.info(f"Initial signal count in MongoDB: {initial_count}")

    # 1. Send initial batch
    await send_signals(500, 0, token)
    
    # 2. Kill worker
    logger.info("KILLING WORKER SERVICE...")
    run_command(["docker", "compose", "stop", "worker"])
    
    # 3. Send more signals while worker is down
    logger.info("Sending signals while worker is DOWN (signals should buffer in Redis)...")
    await send_signals(500, 500, token)
    
    # 4. Verify MongoDB count hasn't increased for the new batch yet
    current_count = await get_mongo_count()
    logger.info(f"Current count in MongoDB (should be near {initial_count + 500}): {current_count}")
    
    # 5. Restart worker
    logger.info("RESTARTING WORKER SERVICE...")
    run_command(["docker", "compose", "start", "worker"])
    
    # 6. Wait for recovery
    logger.info("Waiting 15 seconds for worker to process buffered signals...")
    await asyncio.sleep(15)
    
    # 7. Final validation
    final_count = await get_mongo_count()
    expected = initial_count + 1000
    logger.info(f"Final signal count in MongoDB: {final_count}")
    
    if final_count >= expected:
        logger.info("✅ CHAOS TEST PASSED: All signals recovered and processed.")
    else:
        logger.error(f"❌ CHAOS TEST FAILED: Lost {expected - final_count} signals.")

if __name__ == "__main__":
    asyncio.run(main())
