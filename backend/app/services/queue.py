"""
Queue service — Redis-backed durable ingestion boundary.

WHY REDIS LIST AS QUEUE:
We use Redis LPUSH/BRPOPLPUSH instead of a dedicated message broker because:
  1. Redis is already in the stack (cache + debounce), avoiding another dependency
  2. Sub-millisecond latency for push/pop operations
  3. BRPOPLPUSH provides crash-safe dequeue (see below)
  4. AOF persistence (enabled in docker-compose) survives Redis restarts

WHY BRPOPLPUSH (not simple BRPOP):
  BRPOPLPUSH atomically pops from the main queue AND pushes to a processing list.
  If a worker crashes mid-processing, the message remains in the processing list.
  On restart, recover_processing_queue() moves all stranded messages back to the
  main queue. This gives us AT-LEAST-ONCE delivery semantics.

  Flow:
    signals:queue  →  BRPOPLPUSH  →  signals:processing
    success        →  LREM from signals:processing (ack)
    crash          →  item stays in signals:processing → recovered on restart

DELIVERY GUARANTEE:
  At-least-once. Idempotency in the worker (MongoDB upsert on queue_id) ensures
  that redelivered messages don't create duplicate work items.

LIMITATIONS:
  Redis is single-threaded. At ~50k ops/sec it becomes CPU-bound. For sustained
  10k+ signals/sec, Redis should be replaced with Apache Kafka which provides
  partitioned consumption and disk-backed persistence.
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

    event_id = str(uuid.uuid4())
    payload = signal.model_dump_json()
    envelope = f"{event_id}|{payload}"
    await redis_client.lpush(settings.redis_signal_queue, envelope)
    IMS_QUEUE_DEPTH.set(depth + 1)
    return event_id


async def dequeue_signal(timeout_seconds: int = 5) -> tuple[str, str, SignalIn] | None:
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
    queue_id, payload = raw.split("|", 1)
    IMS_QUEUE_DEPTH.set(await queue_depth())
    return raw, queue_id, SignalIn.model_validate_json(payload)


async def ack_signal(raw: str) -> None:
    """Remove a successfully processed signal from the processing list."""
    await redis_client.lrem(settings.redis_processing_queue, 1, raw)


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
