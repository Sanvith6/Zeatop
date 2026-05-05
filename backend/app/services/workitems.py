import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.orm import selectinload

from app.db.mongo import get_mongo_db
from app.db.postgres import AsyncSessionLocal, retry_postgres_write
from app.db.redis import redis_client
from app.models.db_models import RCA, WorkItem, WorkItemStatusHistory
from app.models.schemas import RCARequest, WorkItemResponse
from app.services.ai_rca import get_ai_rca_suggestion
from app.services.state_machine import InvalidTransitionError, WorkItemStateMachine


severity_rank = case((WorkItem.severity == "P0", 0), (WorkItem.severity == "P1", 1), (WorkItem.severity == "P2", 2), else_=3)


def serialize_work_item(item: WorkItem) -> dict[str, Any]:
    return WorkItemResponse.model_validate(item).model_dump(mode="json")


async def invalidate_workitems_cache() -> None:
    await redis_client.delete("dashboard:workitems:active")
    await redis_client.delete("dashboard:workitems:history")


async def list_workitems(status: str | None = None) -> list[dict[str, Any]]:
    cache_key = "dashboard:workitems:history" if status == "CLOSED" else "dashboard:workitems:active"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    async with AsyncSessionLocal() as session:
        if status == "CLOSED":
            query = select(WorkItem).where(WorkItem.status == "CLOSED").order_by(WorkItem.updated_at.desc())
        else:
            query = select(WorkItem).where(WorkItem.status != "CLOSED").order_by(severity_rank, WorkItem.created_at.desc())
        
        result = await session.execute(query)
        items = [serialize_work_item(item) for item in result.scalars().all()]
    await redis_client.setex(cache_key, 10, json.dumps(items))
    return items


async def get_workitem_detail(work_item_id: uuid.UUID) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WorkItem)
            .where(WorkItem.id == work_item_id)
            .options(selectinload(WorkItem.history), selectinload(WorkItem.rca))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
        data = serialize_work_item(item)
        data["timeline"] = [
            {"from_status": h.from_status, "to_status": h.to_status, "changed_at": h.changed_at.isoformat()} for h in item.history
        ]
        if item.rca:
            data["rca"] = {
                "id": str(item.rca.id),
                "work_item_id": str(item.rca.work_item_id),
                "incident_start": item.rca.incident_start.isoformat(),
                "incident_end": item.rca.incident_end.isoformat(),
                "root_cause_category": item.rca.root_cause_category,
                "fix_applied": item.rca.fix_applied,
                "prevention_steps": item.rca.prevention_steps,
                "submitted_at": item.rca.submitted_at.isoformat(),
                "mttr_minutes": item.mttr_minutes or 0,
            }
        else:
            data["rca"] = None
    signals: list[dict[str, Any]] = []
    cursor = get_mongo_db().signals.find({"work_item_id": str(work_item_id)}).sort("timestamp", -1).limit(500)
    async for signal in cursor:
        signal["_id"] = str(signal["_id"])
        ts = signal.get("timestamp")
        if isinstance(ts, datetime):
            signal["timestamp"] = ts.isoformat()
        signals.append(signal)
    data["signals"] = signals
    return data


async def transition_workitem(work_item_id: uuid.UUID, new_state: str) -> dict[str, Any]:
    async def operation() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(WorkItem)
                    .where(WorkItem.id == work_item_id)
                    .options(selectinload(WorkItem.rca))
                    .with_for_update()
                )
                item = result.scalar_one_or_none()
                if item is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
                previous = item.status
                try:
                    WorkItemStateMachine(item).transition(new_state)
                except InvalidTransitionError as exc:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
                if previous != item.status:
                    item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    session.add(WorkItemStatusHistory(work_item_id=item.id, from_status=previous, to_status=item.status))
            await session.refresh(item)
            payload = serialize_work_item(item)
        await invalidate_workitems_cache()
        
        # Broadcast transition via Redis Pub/Sub
        await redis_client.publish("incidents:updates", json.dumps({
            "type": "INCIDENT_TRANSITIONED",
            "work_item_id": str(work_item_id),
            "new_state": new_state
        }))
        
        return payload

    return await retry_postgres_write(operation)


async def submit_rca(work_item_id: uuid.UUID, payload: RCARequest) -> dict[str, Any]:
    async def operation() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(WorkItem).where(WorkItem.id == work_item_id).with_for_update())
                item = result.scalar_one_or_none()
                if item is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
                if item.status == "CLOSED":
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot submit RCA for a closed work item")
                incident_start = payload.incident_start.astimezone(timezone.utc).replace(tzinfo=None)
                incident_end = payload.incident_end.astimezone(timezone.utc).replace(tzinfo=None)
                if incident_end < incident_start:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Incident end time cannot be before start time"
                    )
                # Requirement 3.3: MTTR based on incident_start and incident_end
                mttr_minutes = (incident_end - incident_start).total_seconds() / 60
                rca = RCA(
                    work_item_id=item.id,
                    incident_start=incident_start,
                    incident_end=incident_end,
                    root_cause_category=payload.root_cause_category.value,
                    fix_applied=payload.fix_applied,
                    prevention_steps=payload.prevention_steps,
                )
                session.add(rca)
                await session.flush()
                item.rca_id = rca.id
                item.mttr_minutes = mttr_minutes
                item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            result_payload = {
                "id": str(rca.id),
                "work_item_id": str(work_item_id),
                "incident_start": rca.incident_start.isoformat(),
                "incident_end": rca.incident_end.isoformat(),
                "root_cause_category": rca.root_cause_category,
                "fix_applied": rca.fix_applied,
                "prevention_steps": rca.prevention_steps,
                "submitted_at": rca.submitted_at.isoformat(),
                "mttr_minutes": mttr_minutes,
            }
        await invalidate_workitems_cache()
        
        # Broadcast RCA submission via Redis Pub/Sub
        await redis_client.publish("incidents:updates", json.dumps({
            "type": "RCA_SUBMITTED",
            "work_item_id": str(work_item_id)
        }))
        
        return result_payload

    return await retry_postgres_write(operation)


async def suggest_ai_rca(work_item_id: uuid.UUID) -> dict[str, Any]:
    detail = await get_workitem_detail(work_item_id)
    return await get_ai_rca_suggestion(
        component_id=detail["component_id"],
        component_type=detail["component_type"],
        severity=detail["severity"],
        signals=detail["signals"]
    )
