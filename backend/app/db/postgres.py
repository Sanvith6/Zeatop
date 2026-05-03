"""
PostgreSQL connection, session management, and retry logic.

WHY POSTGRESQL FOR WORK ITEMS:
PostgreSQL provides the transactional integrity that incident management requires:
  1. ACID transactions: Status transitions, RCA submissions, and MTTR calculations
     must be atomic — a half-applied state change could leave an incident in an
     inconsistent state.
  2. Partial unique index: The `uq_active_work_item_component` index ensures at
     most ONE active incident per component_id. This is our distributed dedup lock
     and it's impossible to implement correctly in MongoDB.
  3. Row-level locking (FOR UPDATE): Prevents race conditions when two workers
     try to increment signal_count simultaneously.
  4. Foreign keys: RCA → WorkItem relationship is enforced at the database level,
     preventing orphaned RCA records.

WHY NOT MongoDB FOR EVERYTHING:
MongoDB lacks true multi-document transactions (or makes them expensive).
The incident lifecycle (state machine transitions, RCA attachment, MTTR calculation)
involves multiple related writes that must succeed or fail together.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine: AsyncEngine = create_async_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,  # Detect stale connections before use
    pool_size=10,         # Connection pool size — tune based on worker count
    max_overflow=5,       # Extra connections allowed during burst
    pool_timeout=10,      # Max wait for a connection from the pool
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_postgres() -> None:
    """
    Create tables and indexes on startup.

    WHY partial unique index:
    `uq_active_work_item_component` is the key to incident deduplication.
    It ensures only ONE non-CLOSED work item can exist per component_id.
    When a worker tries to create a second active incident for the same component,
    PostgreSQL raises IntegrityError, and the worker gracefully falls back to
    incrementing the existing incident's signal count.

    This is more reliable than application-level locking because it works
    correctly even across multiple worker processes and survives process crashes.
    """
    from app.models.db_models import RCA, WorkItem, WorkItemStatusHistory  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_work_item_component
                ON work_items (component_id)
                WHERE status != 'CLOSED'
                """
            )
        )


def is_transient_error(exc: BaseException) -> bool:
    """Check if a database error is transient (worth retrying)."""
    return isinstance(exc, (OperationalError, DBAPIError))


async def retry_postgres_write(
    operation: Callable[[], Awaitable[T]],
    attempts: int = 3,
    on_retry: Callable[[int], None] | None = None,
) -> T:
    """
    Retry a PostgreSQL write operation with exponential backoff.
    """
    delay = 0.15
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if not is_transient_error(exc) or attempt == attempts:
                raise
            last_error = exc
            if on_retry:
                on_retry(attempt)
            logger.warning(
                "Transient PostgreSQL write error, retrying attempt %s/%s: %s",
                attempt, attempts, exc,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("PostgreSQL write retry exhausted") from last_error
