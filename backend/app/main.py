import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import get_settings
from app.db.mongo import get_mongo_db, init_mongo, mongo_client
from app.db.postgres import AsyncSessionLocal, engine, init_postgres
from app.db.redis import init_redis, redis_client
from app.routers.auth import router as auth_router
from app.routers.signals import limiter, router as signals_router
from app.routers.workitems import router as workitems_router
from app.routers.analytics import router as analytics_router
from app.services.ingestion import prometheus_metrics
from app.services.metrics import metrics_logger, metrics_state
from app.services.queue import queue_depth
from app.services.ws_manager import manager, redis_pubsub_listener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres()
    await init_mongo()
    await init_redis()
    metrics_task = asyncio.create_task(metrics_logger())
    ws_task = asyncio.create_task(redis_pubsub_listener())
    try:
        yield
    finally:
        metrics_task.cancel()
        ws_task.cancel()
        await engine.dispose()
        mongo_client.close()
        await redis_client.aclose()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(signals_router)
app.include_router(workitems_router)
app.include_router(analytics_router)
app.include_router(auth_router)


@app.websocket("/ws/incidents")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


@app.get("/health")
async def health() -> dict[str, int | str]:
    return {"status": "ok", "uptime": metrics_state.uptime_seconds()}


@app.get("/ready")
async def readiness() -> dict[str, int | str | dict[str, str]]:
    checks: dict[str, str] = {}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"

        await get_mongo_db().command("ping")
        checks["mongo"] = "ok"

        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks, "error": str(exc)},
        ) from exc

    return {
        "status": "ready",
        "uptime": metrics_state.uptime_seconds(),
        "queue_depth": await queue_depth(),
        "dependencies": checks,
    }


@app.get("/metrics")
async def metrics() -> Response:
    content, media_type = await prometheus_metrics()
    return Response(content=content, media_type=media_type)

@app.post("/mock-alert")
async def mock_alert(payload: dict):
    logging.getLogger("alerts").warning("RECEIVED MOCK ALERT: %s", payload)
    return {"status": "alert_received"}
