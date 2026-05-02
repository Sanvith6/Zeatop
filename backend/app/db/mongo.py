"""
MongoDB connection and initialization.

WHY MONGODB FOR RAW SIGNALS:
MongoDB is used as the append-only log for raw monitoring signals because:
  1. Schema-free: Signals from different monitoring agents may have varying
     fields. MongoDB doesn't require ALTER TABLE for new signal formats.
  2. High write throughput: MongoDB's WiredTiger engine handles burst writes
     efficiently with its document-level locking model.
  3. Natural fit for time-series data: Signals are rarely updated after insert,
     making MongoDB's append-optimized storage ideal.
  4. Separation of concerns: Raw evidence (MongoDB) is kept separate from
     structured incident state (PostgreSQL), so a slow query on raw signals
     doesn't impact work item operations.

WHY NOT PostgreSQL FOR SIGNALS TOO:
Storing millions of raw signals in PostgreSQL would bloat WAL, slow VACUUM,
and compete for connection pool with the transactional work item operations.
MongoDB scales horizontally for reads via replica sets, which PostgreSQL
cannot do natively.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

settings = get_settings()
mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(
    settings.mongo_dsn,
    # Connection pool settings — prevent exhaustion under burst load
    maxPoolSize=50,
    serverSelectionTimeoutMS=5000,
)


def get_mongo_db() -> AsyncIOMotorDatabase:
    return mongo_client[settings.mongo_db]


async def init_mongo() -> None:
    """
    Create indexes on startup — idempotent (IF NOT EXISTS semantics).

    INDEX STRATEGY:
      - component_id: Fast lookup for debounce window queries
      - work_item_id: Fast lookup for incident detail page (linked signals)
      - timestamp: Time-range queries for debounce and dashboard
      - queue_id (unique, sparse): Idempotency key — prevents duplicate inserts
        on redelivered signals. Sparse because not all documents have queue_id
        (e.g., failed_signals).
      - failed_at: Query dead letter queue by failure time
    """
    db = get_mongo_db()
    await db.signals.create_index("component_id")
    await db.signals.create_index("work_item_id")
    await db.signals.create_index("timestamp")
    await db.signals.create_index("queue_id", unique=True, sparse=True)
    # Compound index for debounce queries (component + time range + unlinked)
    await db.signals.create_index([("component_id", 1), ("timestamp", -1)])
    await db.failed_signals.create_index("failed_at")
    await db.failed_signals.create_index("queue_id")
