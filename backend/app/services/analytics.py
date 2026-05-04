from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.mongo import get_mongo_db
from app.db.postgres import AsyncSessionLocal
from app.models.db_models import WorkItem
from sqlalchemy import func, select

async def get_signal_timeseries(minutes: int = 60) -> list[dict[str, Any]]:
    """
    Generate timeseries data for signals ingested per minute.
    
    WHY AGGREGATION PIPELINE:
    MongoDB's aggregation framework is optimized for grouping high-volume 
    documents by time windows. Calculating this in Python would require 
    fetching thousands of documents, which is inefficient.
    """
    db = get_mongo_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    pipeline = [
        {"$match": {"timestamp": {"$gte": since.replace(tzinfo=None)}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%dT%H:%M:00Z", "date": "$timestamp"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    cursor = db.signals.aggregate(pipeline)
    results = []
    async for doc in cursor:
        results.append({"time": doc["_id"], "count": doc["count"]})
    return results

async def get_incident_distribution() -> dict[str, Any]:
    """Get distribution of active incidents by severity and component type."""
    async with AsyncSessionLocal() as session:
        # By Severity
        sev_query = select(WorkItem.severity, func.count(WorkItem.id)).where(WorkItem.status != "CLOSED").group_by(WorkItem.severity)
        sev_res = await session.execute(sev_query)
        by_severity = {row[0]: row[1] for row in sev_res.all()}
        
        # By Type
        type_query = select(WorkItem.component_type, func.count(WorkItem.id)).where(WorkItem.status != "CLOSED").group_by(WorkItem.component_type)
        type_res = await session.execute(type_query)
        by_type = {row[0]: row[1] for row in type_res.all()}
        
    return {
        "by_severity": by_severity,
        "by_type": by_type
    }

async def get_mttr_stats() -> list[dict[str, Any]]:
    """Get historical MTTR trends (average MTTR per day for the last 7 days)."""
    async with AsyncSessionLocal() as session:
        # PostgreSQL doesn't have a direct date_trunc for sqlite/postgres agnostic 
        # but since we are using postgres in compose, we can use it.
        # For simplicity and cross-db compatibility in tests, we'll use a simpler approach.
        query = (
            select(
                func.date(WorkItem.updated_at).label("day"),
                func.avg(WorkItem.mttr_minutes).label("avg_mttr")
            )
            .where(WorkItem.status == "CLOSED", WorkItem.mttr_minutes != None)
            .group_by(func.date(WorkItem.updated_at))
            .order_by("day")
            .limit(7)
        )
        res = await session.execute(query)
        return [{"day": str(row[0]), "avg_mttr": float(row[1])} for row in res.all()]
