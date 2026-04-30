import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine: AsyncEngine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_postgres() -> None:
    from app.models.db_models import RCA, WorkItem, WorkItemStatusHistory  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def is_transient_error(exc: BaseException) -> bool:
    return isinstance(exc, (OperationalError, DBAPIError))


async def retry_postgres_write(operation: Callable[[], Awaitable[T]], attempts: int = 3) -> T:
    delay = 0.15
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if not is_transient_error(exc) or attempt == attempts:
                raise
            last_error = exc
            logger.warning("Transient PostgreSQL write error, retrying attempt %s/%s: %s", attempt, attempts, exc)
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("PostgreSQL write retry exhausted") from last_error
