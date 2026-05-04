"""
Signal ingestion router — the entry point for all monitoring signals.

WHY THIS IS A SEPARATE ROUTER:
The ingestion endpoint has unique concerns (rate limiting, adaptive throttling,
backpressure) that don't apply to work item CRUD. Isolating it keeps the
middleware stack clean and makes it easy to scale ingestion independently.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.models.schemas import SignalAccepted, SignalIn
from app.security import require_auth
from app.services.metrics import metrics_state
from app.services.queue import QueueFullError, enqueue_signal, queue_depth

settings = get_settings()
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.post("", response_model=SignalAccepted, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit)
async def ingest_signal(request: Request, signal: SignalIn, _: str = Depends(require_auth)) -> Response:
    """
    Ingest a monitoring signal into the processing pipeline.

    Flow:
      1. Authenticate (JWT)
      2. Rate limit (per-IP via slowapi + Redis)
      3. Adaptive throttling (check queue pressure)
      4. Enqueue to Redis (returns event_id)
      5. Return 202 Accepted with event_id

    WHY 202 (not 200 or 201):
    The signal is accepted for async processing, NOT processed synchronously.
    202 tells the caller "I got it, I'll handle it later" — this is the standard
    HTTP semantics for async ingestion pipelines.
    """

    # --- Adaptive throttling ---
    # WHY: If the queue is filling up, it means workers can't keep up with
    # ingestion rate. Instead of waiting until the queue is 100% full (503),
    # we start pushing back at 70% capacity with 429 + Retry-After header.
    # This gives upstream producers a softer signal to slow down, preventing
    # the hard cliff of a 503 rejection.
    depth = await queue_depth()
    throttle_threshold = int(settings.queue_max_size * settings.adaptive_throttle_threshold)

    if depth >= throttle_threshold:
        pressure_pct = (depth / settings.queue_max_size) * 100
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Adaptive throttling active — queue at {pressure_pct:.0f}% capacity. Retry shortly.",
            headers={"Retry-After": "5"},
        )

    try:
        event_id = await enqueue_signal(signal)
    except QueueFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    metrics_state.record_ingested()
    return SignalAccepted(status="accepted", event_id=event_id)
