import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import avg, func, select

from app.db.postgres import AsyncSessionLocal
from app.models.db_models import WorkItem

logger = logging.getLogger(__name__)


@dataclass
class MetricsState:
    started_at: float = field(default_factory=time.monotonic)
    ingested_count: int = 0
    last_count: int = 0
    last_tick: float = field(default_factory=time.monotonic)

    def record_ingested(self) -> None:
        self.ingested_count += 1

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def ingestion_rate(self) -> float:
        now = time.monotonic()
        elapsed = max(now - self.last_tick, 0.001)
        rate = (self.ingested_count - self.last_count) / elapsed
        self.last_tick = now
        self.last_count = self.ingested_count
        return rate


metrics_state = MetricsState()


async def metrics_logger(queue: asyncio.Queue) -> None:
    while True:
        await asyncio.sleep(5)
        async with AsyncSessionLocal() as session:
            active_result = await session.execute(
                select(func.count()).select_from(WorkItem).where(WorkItem.status != "CLOSED")
            )
            mttr_result = await session.execute(select(avg(WorkItem.mttr_minutes)).where(WorkItem.mttr_minutes != None))
            active_incidents = active_result.scalar_one()
            avg_mttr = mttr_result.scalar_one() or 0
        logger.info(
            "[METRICS] Signals ingested: %.0f/sec | Queue depth: %s | Active incidents: %s | Avg MTTR: %.0f min",
            metrics_state.ingestion_rate(),
            queue.qsize(),
            active_incidents,
            avg_mttr,
        )
