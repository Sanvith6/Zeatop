from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

settings = get_settings()
mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_dsn)


def get_mongo_db() -> AsyncIOMotorDatabase:
    return mongo_client[settings.mongo_db]


async def init_mongo() -> None:
    db = get_mongo_db()
    await db.signals.create_index("component_id")
    await db.signals.create_index("work_item_id")
    await db.signals.create_index("timestamp")
