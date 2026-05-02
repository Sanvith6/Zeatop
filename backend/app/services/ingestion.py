import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from app.config import get_settings
from app.db.mongo import get_mongo_db
from app.db.postgres import AsyncSessionLocal, retry_postgres_write
from app.db.redis import redis_client
from app.models.schemas import SignalIn
from app.models.db_models import WorkItem, WorkItemStatusHistory
from app.services.alerts import get_alert_strategy
from app.services.circuit_breaker import CircuitOpenError, mongo_breaker, postgres_breaker
from app.services.classifier import classify_severity
from app.services.metrics import metrics_state
from app.services.queue import ack_signal, dequeue_signal, queue_depth
from app.services.workitems import invalidate_workitems_cache

logger = logging.getLogger(__name__)
settings = get_settings()
MAX_PROCESSING_ATTEMPTS = 3


def signal_to_document(signal: SignalIn, queue_id: str) -> dict[str, object]:
    """Convert a Pydantic signal into a MongoDB document."""
    return {
        "queue_id": queue_id,
        "component_id": signal.component_id,
        "component_type": signal.component_type.value,
        "error_message": signal.error_message,
        "severity": signal.severity.value,
        "timestamp": signal.timestamp.astimezone(timezone.utc).replace(tzinfo=None),
        "work_item_id": None,
        "enqueued_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }


async def worker_loop(worker_id: int) -> None:
    """Main worker loop — continuously dequeue and process signals."""
    logger.info("Worker %d: STARTED", worker_id)
    while True:
        try:
            message = await dequeue_signal()
            if message is None:
                continue
            
            raw, queue_id, signal = message
            logger.info("Worker %d: POPPED signal %s for %s", worker_id, queue_id, signal.component_id)
            
            dequeue_time = time.monotonic()
            await process_with_retries(worker_id, raw, queue_id, signal, dequeue_time)
            
        except Exception as exc:
            logger.exception("Worker %d: LOOP CRASH: %s", worker_id, str(exc))
            await asyncio.sleep(1)


async def process_with_retries(
    worker_id: int, raw: str, queue_id: str, signal: SignalIn, dequeue_time: float
) -> None:
    """Process a signal with retry logic and DLQ fallback."""
    for attempt in range(1, MAX_PROCESSING_ATTEMPTS + 1):
        try:
            logger.info("Worker %d: Attempt %d/3 for signal %s", worker_id, attempt, queue_id)
            await process_signal(signal, queue_id)
            
            # SUCCESS
            await ack_signal(raw)
            processing_time = time.monotonic() - dequeue_time
            metrics_state.record_processed(latency_seconds=processing_time)
            logger.info("Worker %d: SUCCESS signal %s", worker_id, queue_id)
            return
            
        except CircuitOpenError as exc:
            logger.warning("Worker %d: CIRCUIT OPEN for signal %s", worker_id, queue_id)
            break # Go to DLQ
        except Exception as exc:
            logger.warning("Worker %d: ERROR on signal %s (attempt %d): %r", worker_id, queue_id, attempt, exc)
            if attempt < MAX_PROCESSING_ATTEMPTS:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                continue

    # DLQ Fallback
    logger.error("Worker %d: SIGNAL %s FAILED after all attempts. Moving to DLQ.", worker_id, queue_id)
    await store_failed_signal(raw, queue_id, signal, "Exhausted retries")
    await ack_signal(raw)


async def process_signal(signal: SignalIn, queue_id: str) -> None:
    """Core signal processing: store in MongoDB, resolve work item in PostgreSQL."""
    db = get_mongo_db()

    # 1. Classification
    from app.models.schemas import Severity
    effective_severity = classify_severity(signal.component_type.value, signal.severity.value)
    if effective_severity != signal.severity.value:
        signal = signal.model_copy(update={"severity": Severity(effective_severity)})

    document = signal_to_document(signal, queue_id)

    # 2. MongoDB Persistence (Idempotent)
    async def mongo_write():
        return await db.signals.update_one(
            {"queue_id": queue_id},
            {"$setOnInsert": document},
            upsert=True,
        )

    insert_result = await mongo_breaker.call(mongo_write)
    
    # 3. Resolve Work Item
    work_item_id = await resolve_work_item(signal, queue_id)
    
    if work_item_id:
        # Link the signal to the work item
        await db.signals.update_one(
            {"queue_id": queue_id},
            {"$set": {"work_item_id": str(work_item_id)}}
        )


async def resolve_work_item(signal: SignalIn, queue_id: str) -> UUID | None:
    """Determine whether this signal should create or update a work item."""
    # Step 1: Check for existing active work item
    open_id = await get_existing_workitem_id(signal.component_id)
    if open_id:
        logger.info("  -> Found existing open work item %s for %s", open_id, signal.component_id)
        await increment_signal_count(open_id, signal)
        return open_id

    # Step 2: Add to debounce window in Redis
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=10)
    debounce_key = f"debounce_window:{signal.component_id}"
    score = int(now.timestamp() * 1000)
    
    await redis_client.zadd(debounce_key, {queue_id: score})
    await redis_client.zremrangebyscore(debounce_key, 0, int(threshold.timestamp() * 1000))
    await redis_client.expire(debounce_key, 20)
    
    window_size = int(await redis_client.zcard(debounce_key))
    logger.info("  -> Component %s window size: %d", signal.component_id, window_size)

    # Step 3: Threshold reached (10 signals) -> create work item
    if window_size >= 10:
        logger.info("  -> THRESHOLD REACHED for %s (size %d)", signal.component_id, window_size)
        
        # Check cache to avoid race conditions
        cached_id = await redis_client.get(f"debounce:{signal.component_id}")
        if cached_id:
            logger.info("  -> Using cached work item %s", cached_id)
            parsed = UUID(cached_id)
            await increment_signal_count(parsed, signal)
            return parsed

        # Create new work item
        work_item_id = await create_work_item(signal, window_size)
        logger.info("  -> CREATED NEW WORK ITEM: %s", work_item_id)
        
        await redis_client.setex(f"debounce:{signal.component_id}", 10, str(work_item_id))

        # Link all signals in the window to the new work item in MongoDB
        # Note: In a high-traffic system, this would be a background task
        await get_mongo_db().signals.update_many(
            {
                "component_id": signal.component_id,
                "work_item_id": None,
                "enqueued_at": {"$gte": threshold.replace(tzinfo=None)},
            },
            {"$set": {"work_item_id": str(work_item_id)}},
        )
        await redis_client.delete(debounce_key)

        # Trigger alerts
        try:
            await get_alert_strategy(signal.component_type.value).alert(signal, str(work_item_id))
        except Exception:
            logger.error("  -> Alert failed for %s", work_item_id)
            
        return work_item_id

    return None


async def get_existing_workitem_id(component_id: str) -> UUID | None:
    """Check PostgreSQL for an active (non-CLOSED) work item."""
    async def operation():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(WorkItem.id)
                .where(WorkItem.component_id == component_id, WorkItem.status != "CLOSED")
                .order_by(WorkItem.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    return await asyncio.wait_for(
        postgres_breaker.call(operation),
        timeout=settings.db_call_timeout,
    )


async def create_work_item(signal: SignalIn, signal_count: int) -> UUID:
    """Create a new work item in PostgreSQL with transactional integrity."""
    async def operation() -> UUID:
        async with AsyncSessionLocal() as session:
            try:
                async with session.begin():
                    item = WorkItem(
                        component_id=signal.component_id,
                        component_type=signal.component_type.value,
                        severity=signal.severity.value,
                        signal_count=signal_count,
                    )
                    session.add(item)
                    await session.flush()
                    session.add(
                        WorkItemStatusHistory(
                            work_item_id=item.id,
                            from_status=None,
                            to_status="OPEN",
                        )
                    )
                    work_item_id = item.id
                    return work_item_id
            except IntegrityError:
                # Race condition: another worker created it first.
                await session.rollback()
                existing_id = await get_existing_workitem_id(signal.component_id)
                if existing_id is None:
                    raise
                await increment_signal_count(existing_id, signal)
                return existing_id

    await invalidate_workitems_cache()
    return await asyncio.wait_for(
        retry_postgres_write(operation),
        timeout=settings.db_call_timeout * MAX_PROCESSING_ATTEMPTS,
    )


async def increment_signal_count(work_item_id: UUID, signal: SignalIn) -> None:
    """Atomically increment the signal count and potentially upgrade severity."""
    async def operation() -> None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(WorkItem).where(WorkItem.id == work_item_id).with_for_update()
                )
                item = result.scalar_one_or_none()
                if item:
                    item.signal_count += 1
                    if severity_value(signal.severity.value) < severity_value(item.severity):
                        item.severity = signal.severity.value
                    item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await retry_postgres_write(operation)
    await invalidate_workitems_cache()


def severity_value(severity: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(severity, 99)


async def store_failed_signal(raw: str, queue_id: str, signal: SignalIn, error: object) -> None:
    """DLQ for failed signals."""
    await get_mongo_db().failed_signals.insert_one({
        "queue_id": queue_id,
        "raw_payload": raw,
        "signal": signal.model_dump(mode="json"),
        "failure_reason": repr(error),
        "failed_at": datetime.now(timezone.utc).replace(tzinfo=None),
    })


async def prometheus_metrics() -> tuple[bytes, str]:
    from app.services.metrics import IMS_QUEUE_DEPTH
    IMS_QUEUE_DEPTH.set(await queue_depth())
    return generate_latest(), CONTENT_TYPE_LATEST
