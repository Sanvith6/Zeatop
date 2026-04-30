import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.db.mongo import get_mongo_db
from app.db.postgres import AsyncSessionLocal, retry_postgres_write
from app.db.redis import redis_client
from app.models.db_models import WorkItem, WorkItemStatusHistory
from app.models.schemas import SignalIn
from app.services.alerts import get_alert_strategy
from app.services.queue import signal_queue
from app.services.workitems import invalidate_workitems_cache

logger = logging.getLogger(__name__)
component_windows: dict[str, deque[datetime]] = defaultdict(deque)
component_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def signal_to_document(signal: SignalIn) -> dict[str, object]:
    return {
        "component_id": signal.component_id,
        "component_type": signal.component_type.value,
        "error_message": signal.error_message,
        "severity": signal.severity.value,
        "timestamp": signal.timestamp.astimezone(timezone.utc).replace(tzinfo=None),
        "work_item_id": None,
    }


async def worker_loop() -> None:
    while True:
        signal = await signal_queue.get()
        try:
            await process_signal(signal)
        except Exception:
            logger.exception("Failed to process signal for component %s", signal.component_id)
        finally:
            signal_queue.task_done()


async def process_signal(signal: SignalIn) -> None:
    db = get_mongo_db()
    insert_result = await db.signals.insert_one(signal_to_document(signal))
    work_item_id = await resolve_work_item(signal)
    if work_item_id:
        await db.signals.update_one({"_id": insert_result.inserted_id}, {"$set": {"work_item_id": str(work_item_id)}})


async def resolve_work_item(signal: SignalIn) -> UUID | None:
    async with component_locks[signal.component_id]:
        open_id = await get_existing_workitem_id(signal.component_id)
        if open_id:
            await increment_signal_count(open_id, signal)
            await redis_client.setex(f"debounce:{signal.component_id}", 10, str(open_id))
            return open_id

        now = datetime.now(timezone.utc)
        window = component_windows[signal.component_id]
        window.append(now)
        threshold = now - timedelta(seconds=10)
        while window and window[0] < threshold:
            window.popleft()

        if len(window) >= 100:
            cached_id = await redis_client.get(f"debounce:{signal.component_id}")
            if cached_id:
                parsed = UUID(cached_id)
                await increment_signal_count(parsed, signal)
                return parsed
            work_item_id = await create_work_item(signal, len(window))
            await redis_client.setex(f"debounce:{signal.component_id}", 10, str(work_item_id))
            await get_mongo_db().signals.update_many(
                {
                    "component_id": signal.component_id,
                    "work_item_id": None,
                    "timestamp": {"$gte": threshold.replace(tzinfo=None)},
                },
                {"$set": {"work_item_id": str(work_item_id)}},
            )
            window.clear()
            await get_alert_strategy(signal.component_type.value).alert(signal, str(work_item_id))
            return work_item_id
    return None


async def get_existing_workitem_id(component_id: str) -> UUID | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WorkItem.id)
            .where(WorkItem.component_id == component_id, WorkItem.status != "CLOSED")
            .order_by(WorkItem.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def create_work_item(signal: SignalIn, signal_count: int) -> UUID:
    async def operation() -> UUID:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                item = WorkItem(
                    component_id=signal.component_id,
                    component_type=signal.component_type.value,
                    severity=signal.severity.value,
                    signal_count=signal_count,
                )
                session.add(item)
                await session.flush()
                session.add(WorkItemStatusHistory(work_item_id=item.id, from_status=None, to_status="OPEN"))
                work_item_id = item.id
        await invalidate_workitems_cache()
        return work_item_id

    return await retry_postgres_write(operation)


async def increment_signal_count(work_item_id: UUID, signal: SignalIn) -> None:
    async def operation() -> None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(WorkItem).where(WorkItem.id == work_item_id).with_for_update())
                item = result.scalar_one_or_none()
                if item is None:
                    return
                item.signal_count += 1
                if severity_value(signal.severity.value) < severity_value(item.severity):
                    item.severity = signal.severity.value
                item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await retry_postgres_write(operation)
    await invalidate_workitems_cache()


def severity_value(severity: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(severity, 99)


async def prometheus_metrics() -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(WorkItem.status, WorkItem.severity, WorkItem.signal_count))
        items = result.all()
    active = sum(1 for status, _, _ in items if status != "CLOSED")
    total_signals = sum(signal_count for _, _, signal_count in items)
    queue_depth = signal_queue.qsize()
    return "\n".join(
        [
            "# HELP ims_active_incidents Number of active incidents",
            "# TYPE ims_active_incidents gauge",
            f"ims_active_incidents {active}",
            "# HELP ims_queue_depth Current in-process queue depth",
            "# TYPE ims_queue_depth gauge",
            f"ims_queue_depth {queue_depth}",
            "# HELP ims_workitem_linked_signals Total signals linked to work items",
            "# TYPE ims_workitem_linked_signals counter",
            f"ims_workitem_linked_signals {total_signals}",
            "",
        ]
    )
