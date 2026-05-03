"""
Queue service — Redis-backed durable ingestion boundary.

Uses Redis LPUSH / BRPOPLPUSH for low-latency, crash-safe buffering. 
The BRPOPLPUSH pattern ensures at-least-once delivery by atomically moving 
messages to a processing list before consumption. Stranded messages from 
worker crashes are recovered on startup.

Limitations: Redis is single-threaded (~50k ops/sec). For extreme throughput 
(100k+), migration to a partitioned broker like Kafka is recommended.
"""

import logging
import uuid

from app.config import get_settings
from app.db.redis import redis_client
from app.models.schemas import SignalIn
from app.services.metrics import IMS_QUEUE_DEPTH

settings = get_settings()
logger = logging.getLogger(__name__)


async def enqueue_signal(signal: SignalIn) -> str:
    """
    Push a signal to the Redis ingestion queue.

    Returns the generated event_id (UUID) so the caller can track the signal
    through the pipeline and correlate it in logs.

    Raises QueueFullError if the queue has reached max capacity (backpressure).
    """
    depth = await queue_depth()

    # --- Backpressure threshold warnings ---
    # Log at increasing severity as the queue fills up. This gives operators
    # early warning before the queue saturates and starts rejecting signals.
    warn_level = int(settings.queue_max_size * settings.queue_warn_threshold)
    critical_level = int(settings.queue_max_size * settings.queue_critical_threshold)

    if depth >= settings.queue_max_size:
        raise QueueFullError("Ingestion queue is saturated; retry shortly")
    elif depth >= critical_level:
        logger.critical(
            "Queue depth CRITICAL: %d/%d (%.0f%%) — approaching saturation",
            depth, settings.queue_max_size, (depth / settings.queue_max_size) * 100,
        )
    elif depth >= warn_level:
        logger.warning(
            "Queue depth elevated: %d/%d (%.0f%%) — monitor closely",
            depth, settings.queue_max_size, (depth / settings.queue_max_size) * 100,
        )

    import time
    event_id = str(uuid.uuid4())
    payload = signal.model_dump_json()
    envelope = f"{event_id}|{time.time()}|{payload}"
    await redis_client.lpush(settings.redis_signal_queue, envelope)
    IMS_QUEUE_DEPTH.set(depth + 1)
    return event_id


async def dequeue_signal(timeout_seconds: int = 5) -> tuple[str, str, float, SignalIn] | None:
    """
    Block-pop a signal from the queue into the processing list.

    Uses BRPOPLPUSH for crash-safe dequeue:
    - Atomically removes from main queue and adds to processing list
    - If worker crashes, message stays in processing list for recovery
    - On success, ack_signal() removes it from the processing list
    """
    raw = await redis_client.brpoplpush(
        settings.redis_signal_queue,
        settings.redis_processing_queue,
        timeout=timeout_seconds,
    )
    if raw is None:
        return None
    
    parts = raw.split("|", 2)
    if len(parts) == 3:
        queue_id, enqueued_at, payload = parts
        enqueued_at = float(enqueued_at)
    else:
        # Compatibility for old format messages
        queue_id, payload = raw.split("|", 1)
        import time
        enqueued_at = time.time()
        
    IMS_QUEUE_DEPTH.set(await queue_depth())
    return raw, queue_id, enqueued_at, SignalIn.model_validate_json(payload)


async def ack_signal(raw: str) -> None:
    """Remove a successfully processed signal from the processing list."""
    await redis_client.lrem(settings.redis_processing_queue, 1, raw)


async def ack_signals_bulk(raw_list: list[str]) -> None:
    """Remove multiple successfully processed signals from the processing list in one transaction."""
    if not raw_list:
        return
    async with redis_client.pipeline(transaction=True) as pipe:
        for raw in raw_list:
            pipe.lrem(settings.redis_processing_queue, 1, raw)
        await pipe.execute()


async def recover_processing_queue() -> None:
    """
    Crash recovery — move stranded messages back to the main queue.

    WHY THIS IS NEEDED:
    A restart (or OOM kill) can leave messages in the processing list after
    BRPOPLPUSH. Without recovery, those accepted signals would be silently lost.
    This function runs once at worker startup and moves everything back to the
    main queue so another worker iteration can retry them.

    This is the key mechanism that provides our at-least-once delivery guarantee.
    Combined with idempotency checks (MongoDB upsert on queue_id), redelivered
    signals are safely deduplicated.
    """
    recovered = 0
    while await redis_client.llen(settings.redis_processing_queue):
        await redis_client.rpoplpush(settings.redis_processing_queue, settings.redis_signal_queue)
        recovered += 1
    if recovered:
        logger.warning("Recovered %d stranded signals from processing queue", recovered)
    IMS_QUEUE_DEPTH.set(await queue_depth())


async def queue_depth() -> int:
    """Current number of signals waiting in the main queue."""
    return int(await redis_client.llen(settings.redis_signal_queue))


class QueueFullError(RuntimeError):
    """Raised when the ingestion queue is at capacity (backpressure signal)."""
    pass
