from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.models.schemas import SignalAccepted, SignalIn
from app.services.metrics import metrics_state
from app.services.queue import signal_queue

settings = get_settings()
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.post("", response_model=SignalAccepted, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit)
async def ingest_signal(request: Request, signal: SignalIn) -> SignalAccepted:
    try:
        signal_queue.put_nowait(signal)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion queue is saturated; retry shortly",
        ) from exc
    metrics_state.record_ingested()
    return SignalAccepted(status="accepted")
