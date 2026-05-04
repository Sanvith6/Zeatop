from fastapi import APIRouter, Depends
from typing import Any

from app.security import require_auth
from app.services.analytics import get_signal_timeseries, get_incident_distribution, get_mttr_stats

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(require_auth)])

@router.get("/signals/timeseries")
async def signal_timeseries(minutes: int = 60) -> list[dict[str, Any]]:
    return await get_signal_timeseries(minutes)

@router.get("/incidents/distribution")
async def incident_distribution() -> dict[str, Any]:
    return await get_incident_distribution()

@router.get("/mttr/history")
async def mttr_history() -> list[dict[str, Any]]:
    return await get_mttr_stats()
