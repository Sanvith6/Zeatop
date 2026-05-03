import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pymongo import UpdateOne
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, update
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
from app.services.queue import ack_signal, ack_signals_bulk, dequeue_signal, queue_depth
from app.services.workitems import invalidate_workitems_cache

logger = logging.getLogger(__name__)
settings = get_settings()

@dataclass
class BatchBuffer:
    raw_signals: list[str] = field(default_factory=list)
    signals: list[tuple[str, SignalIn]] = field(default_factory=list)
    last_flush: float = field(default_factory=time.monotonic)

    def is_ready(self) -> bool:
        return (
            len(self.raw_signals) >= settings.worker_batch_size
            or (time.monotonic() - self.last_flush) >= settings.worker_batch_timeout
        )

    def clear(self):
        self.raw_signals.clear()
        self.signals.clear()
        self.last_flush = time.monotonic()
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
    """Main worker loop — collects signals into batches and flushes them."""
    logger.info("Worker %d: STARTED", worker_id)
    buffer = BatchBuffer()
    
    while True:
        try:
            # 1. Try to dequeue a signal (non-blocking if possible, but BRPOPLPUSH is blocking)
            message = await dequeue_signal(timeout_seconds=1)
            if message:
                raw, queue_id, enqueued_at, signal = message
                buffer.raw_signals.append(raw)
                buffer.signals.append((queue_id, signal))
                
                # Record queue wait time
                wait_time = time.time() - enqueued_at
                metrics_state.record_queue_wait(wait_time)
                logger.debug("Worker %d: Buffered signal %s (waited %.3fs)", worker_id, queue_id, wait_time)

            # 2. Check if batch is ready for flush
            if buffer.signals and buffer.is_ready():
                await flush_batch(worker_id, buffer)
                buffer.clear()
            
            # 3. Small sleep if no message to prevent busy-looping
            if message is None and not buffer.signals:
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            # Coordinated shutdown: flush whatever is left in the buffer
            if buffer.signals:
                logger.info("Worker %d: Flushing buffer before shutdown...", worker_id)
                await flush_batch(worker_id, buffer)
            break
        except Exception as exc:
            logger.exception("Worker %d: LOOP CRASH: %s", worker_id, str(exc))
            await asyncio.sleep(1)


async def flush_batch(worker_id: int, buffer: BatchBuffer) -> None:
    """Flush a batch of signals to Mongo and Postgres."""
    start_time = time.monotonic()
    count = len(buffer.signals)
    logger.info("Worker %d: Flushing batch of %d signals...", worker_id, count)
    
    try:
        # Step 1: Bulk Record to MongoDB (Idempotent)
        await record_signals_bulk(buffer.signals)
        
        # Step 2: Process Work Items (Batch Logic)
        # Note: This still uses the debouncing logic per signal, 
        # but wraps updates in fewer transactions where possible.
        for queue_id, signal in buffer.signals:
            await resolve_work_item(signal, queue_id, worker_id)
            
        # Step 3: Bulk Ack in Redis
        await ack_signals_bulk(buffer.raw_signals)
        
        latency = time.monotonic() - start_time
        metrics_state.record_processed(latency_seconds=latency)
        logger.info("Worker %d: SUCCESS batch flush (%d signals) in %.3fs", worker_id, count, latency)
        
    except CircuitOpenError:
        logger.warning("Worker %d: CIRCUIT OPEN during batch flush — signals remain in processing queue", worker_id)
        # We don't ACK, so signals stay in the processing list and will be recovered or retried.
        # However, for production we should move to DLQ if they keep failing.
        # To keep it simple and safe: just let them stay for now.
    except Exception as exc:
        logger.error("Worker %d: BATCH FLUSH ERROR: %r", worker_id, exc)


async def record_signals_bulk(signals: list[tuple[str, SignalIn]]) -> None:
    """Perform bulk upsert to MongoDB."""
    db = get_mongo_db()
    ops = []
    for queue_id, signal in signals:
        # Classification
        from app.models.schemas import Severity
        effective_severity = classify_severity(signal.component_type.value, signal.severity.value)
        if effective_severity != signal.severity.value:
            signal = signal.model_copy(update={"severity": Severity(effective_severity)})
            
        doc = signal_to_document(signal, queue_id)
        ops.append(UpdateOne(
            {"queue_id": queue_id},
            {"$setOnInsert": doc},
            upsert=True
        ))
    
    if ops:
        start = time.monotonic()
        await mongo_breaker.call(db.signals.bulk_write, ops, ordered=False)
        metrics_state.record_db_latency("mongodb", time.monotonic() - start)


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


async def resolve_work_item(signal: SignalIn, queue_id: str, worker_id: int = 0) -> UUID | None:
    """Determine whether this signal should create or update a work item."""
    # Step 1: Check Redis cache for active work item (Fastest path)
    # This prevents hammering Postgres during high-throughput bursts for the same component.
    cached_id = await redis_client.get(f"debounce:{signal.component_id}")
    if cached_id:
        parsed_id = UUID(cached_id.decode() if isinstance(cached_id, bytes) else cached_id)
        await increment_signal_count(parsed_id, signal, worker_id)
        return parsed_id

    # Step 2: Check PostgreSQL for an existing active work item (Slow path)
    # If found, we cache it in Redis to avoid subsequent DB queries for this component.
    open_id = await get_existing_workitem_id(signal.component_id)
    if open_id:
        await redis_client.setex(f"debounce:{signal.component_id}", 10, str(open_id))
        await increment_signal_count(open_id, signal, worker_id)
        return open_id

    # Step 3: Threshold/Debounce window in Redis
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=10)
    debounce_key = f"debounce_window:{signal.component_id}"
    score = int(now.timestamp() * 1000)
    
    await redis_client.zadd(debounce_key, {queue_id: score})
    await redis_client.zremrangebyscore(debounce_key, 0, int(threshold.timestamp() * 1000))
    await redis_client.expire(debounce_key, 20)
    
    window_size = int(await redis_client.zcard(debounce_key))
    
    # Step 4: Threshold reached (100 signals) -> create new work item
    if window_size >= 100:
        logger.info("  -> THRESHOLD REACHED for %s (size %d)", signal.component_id, window_size)
        
        # Double-check cache to prevent race condition during creation
        cached_id = await redis_client.get(f"debounce:{signal.component_id}")
        if cached_id:
            parsed = UUID(cached_id.decode() if isinstance(cached_id, bytes) else cached_id)
            await increment_signal_count(parsed, signal, worker_id)
            return parsed

        # Create new work item
        work_item_id = await create_work_item(signal, window_size, worker_id)
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


async def create_work_item(signal: SignalIn, signal_count: int, worker_id: int = 0) -> UUID:
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
    start = time.monotonic()
    res = await asyncio.wait_for(
        retry_postgres_write(
            operation, 
            on_retry=lambda _: metrics_state.record_retry(worker_id)
        ),
        timeout=settings.db_call_timeout * MAX_PROCESSING_ATTEMPTS,
    )
    metrics_state.record_db_latency("postgresql", time.monotonic() - start)
    
    # Broadcast new incident via Redis Pub/Sub for real-time UI updates
    await redis_client.publish("incidents:updates", json.dumps({
        "type": "INCIDENT_CREATED",
        "work_item_id": str(res)
    }))
    
    return res


async def increment_signal_count(work_item_id: UUID, signal: SignalIn, worker_id: int = 0) -> None:
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

    await retry_postgres_write(
        operation, 
        on_retry=lambda _: metrics_state.record_retry(worker_id)
    )
    await invalidate_workitems_cache()
    
    # Broadcast update via Redis Pub/Sub for real-time UI updates
    await redis_client.publish("incidents:updates", json.dumps({
        "type": "INCIDENT_UPDATED",
        "work_item_id": str(work_item_id)
    }))


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
