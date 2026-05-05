"""
Standalone worker process — consumes signals from the Redis queue.

WHY A SEPARATE CONTAINER (not background tasks in FastAPI):
  1. FAULT ISOLATION: If a worker crashes (OOM, unhandled exception), the API
     continues accepting signals. Signals are safely queued in Redis.
  2. HORIZONTAL SCALING: `docker-compose up --scale worker=10` adds processing
     capacity without adding API instances. Scale consumers independently.
  3. RESOURCE ISOLATION: Heavy DB writes don't compete with API I/O for CPU
     and memory. The API stays fast under worker load.
  4. INDEPENDENT RESTARTS: Workers can be restarted (for deploys or recovery)
     without dropping any incoming signals.

CRASH RECOVERY:
  On startup, `recover_processing_queue()` moves any signals stranded in the
  processing list (from a previous crash) back to the main queue. This ensures
  at-least-once delivery even through worker crashes.

GRACEFUL SHUTDOWN:
  On SIGTERM/SIGINT, worker tasks are cancelled. The `finally` block ensures
  database connections are cleaned up. In-flight signals remain in the Redis
  processing list and will be recovered on next startup.
"""

import asyncio
import logging
import signal

from prometheus_client import start_http_server
from app.config import get_settings
from app.db.mongo import init_mongo, mongo_client
from app.db.postgres import engine, init_postgres
from app.db.redis import init_redis, redis_client
from app.services.ingestion import worker_loop
from app.services.queue import recover_processing_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("worker")
settings = get_settings()

# Flag for coordinated shutdown across all worker tasks
_shutdown_event = asyncio.Event()


async def main():
    logger.info("Initializing databases for worker...")
    await init_postgres()
    await init_mongo()
    await init_redis()

    # Start Prometheus metrics server on port 8001
    # This allows Prometheus to scrape the worker's counters and histograms
    logger.info("Starting Prometheus metrics server on port 8001...")
    start_http_server(8001)

    logger.info("Recovering processing queue (crash recovery)...")
    await recover_processing_queue()

    logger.info(
        "Starting %d worker tasks (concurrency=%d)...",
        settings.worker_concurrency, settings.worker_concurrency,
    )
    workers = [
        asyncio.create_task(worker_loop(index + 1))
        for index in range(settings.worker_concurrency)
    ]

    # --- Graceful shutdown handler ---
    def handle_signal():
        logger.info("RECEIVED SHUTDOWN SIGNAL (SIGTERM/SIGINT)")
        _shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    try:
        # Wait until shutdown is requested
        await _shutdown_event.wait()
        logger.info("Shutdown event triggered — stopping workers gracefully...")
    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    finally:
        logger.info("Shutting down worker connections...")
        for task in workers:
            task.cancel()
        # Wait for tasks to finish their current signal (if any)
        await asyncio.gather(*workers, return_exceptions=True)
        await engine.dispose()
        mongo_client.close()
        await redis_client.aclose()
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
