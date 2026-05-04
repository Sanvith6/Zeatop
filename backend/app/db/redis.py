"""
Redis connection initialization.

WHY REDIS (triple role):
Redis serves three distinct purposes in this system:

  1. INGESTION QUEUE: Redis lists (LPUSH/BRPOPLPUSH) act as the bounded buffer
     between the API and workers. Sub-millisecond push latency ensures the API
     can return 202 without blocking.

  2. DEBOUNCE CACHE: Redis sorted sets store per-component signal counts within
     sliding time windows. Atomic operations (ZADD, ZCARD, EXPIRE) make this
     safe under concurrent worker access without application-level locks.

  3. DASHBOARD CACHE: The work items list is cached in Redis for 10 seconds to
     avoid hammering PostgreSQL on every dashboard refresh. This is a simple
     cache-aside pattern with lazy invalidation on writes.

WHY NOT SEPARATE REDIS INSTANCES:
For this scale, a single Redis instance handles all three roles easily.
In production at 10k+ signals/sec, you'd separate the queue Redis from the
cache Redis to prevent cache eviction from affecting queue durability.

DURABILITY:
Redis is configured with AOF (Append-Only File) persistence in docker-compose:
  `redis-server --appendonly yes`
This means every write is appended to disk. On restart, Redis replays the AOF
to recover queued signals. Combined with the processing queue recovery logic,
this provides durable at-least-once delivery even through Redis restarts.

COLD START:
On first boot, Redis starts with an empty dataset. The dashboard cache is
rebuilt lazily from PostgreSQL on the first request. The debounce windows
start fresh, which is correct behavior — there's no stale state to recover.
"""

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()
redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=20,     # Increased to accommodate blocking pops
    socket_timeout=20,             # Must be > brpoplpush timeout
    retry_on_timeout=True,         # Auto-retry on timeout (idempotent ops)
)


async def init_redis() -> None:
    """Verify Redis connectivity on startup."""
    await redis_client.ping()
