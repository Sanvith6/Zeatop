"""
Observability metrics — Prometheus counters, gauges, and histograms.

WHY PROMETHEUS FORMAT:
Prometheus is the industry standard for cloud-native metrics. Its pull-based
model works naturally with Kubernetes service discovery, and tools like Grafana
can visualize the data without custom dashboards. Even without a Prometheus
server, the /metrics endpoint provides a human-readable snapshot of system health.

WHY THESE SPECIFIC METRICS:
  - ims_signals_ingested_total: How fast are signals arriving? (throughput)
  - ims_signals_processed_total: How fast are workers consuming? (capacity)
  - ims_signals_failed_total: Are retries exhausting? (error rate / DLQ growth)
  - ims_queue_depth: Is backpressure building? (queue saturation)
  - ims_signal_processing_seconds: How long does each signal take? (latency SLO)
  - ims_circuit_breaker_state: Are dependencies healthy? (resilience state)

These metrics directly map to the four golden signals (latency, traffic, errors,
saturation) recommended by the Google SRE book.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select

from app.db.postgres import AsyncSessionLocal
from app.models.db_models import WorkItem

logger = logging.getLogger(__name__)

# --- Prometheus metric definitions ---

IMS_SIGNALS_INGESTED_TOTAL = Counter(
    "ims_signals_ingested_total",
    "Signals accepted into the ingestion queue",
)
IMS_SIGNALS_PROCESSED_TOTAL = Counter(
    "ims_signals_processed_total",
    "Signals successfully processed by workers",
)
IMS_SIGNALS_FAILED_TOTAL = Counter(
    "ims_signals_failed_total",
    "Signals sent to dead letter storage after retries",
)
IMS_QUEUE_DEPTH = Gauge(
    "ims_queue_depth",
    "Current Redis ingestion queue depth",
)
IMS_PROCESSING_RATE = Gauge(
    "ims_processing_rate_per_second",
    "Current processing rate (signals/sec) calculated over 5s intervals",
)

# WHY HISTOGRAM (not Summary):
# Histograms are aggregatable across instances and support percentile
# calculations server-side. Summaries compute percentiles on the client
# which breaks when you have multiple worker replicas.
IMS_PROCESSING_LATENCY = Histogram(
    "ims_signal_processing_seconds",
    "Time to process a single signal end-to-end (dequeue to completion)",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

IMS_QUEUE_WAIT_TIME = Histogram(
    "ims_signal_queue_wait_seconds",
    "Time a signal spent waiting in the queue before being picked up",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

IMS_CIRCUIT_BREAKER_STATE = Gauge(
    "ims_circuit_breaker_state",
    "Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)",
    ["dependency"],
)
IMS_RETRY_TOTAL = Counter(
    "ims_retry_total",
    "Total number of processing retries attempted",
    ["worker_id"],
)
IMS_DB_WRITE_LATENCY = Histogram(
    "ims_db_write_latency_seconds",
    "Database write latency for Mongo and Postgres",
    ["db_type"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
IMS_AI_RCA_REQUESTS_TOTAL = Counter(
    "ims_ai_rca_requests_total",
    "Total number of AI-powered RCA suggestions requested",
    ["status"],
)


@dataclass
class MetricsState:
    """
    In-process metrics state for throughput logging.

    WHY in-process instead of only Prometheus:
    Prometheus scrapes on intervals (typically 15-30s). Structured log lines
    every 5 seconds give operators immediate visibility in container logs
    without needing a Prometheus server — critical during initial setup and
    incident debugging.
    """
    started_at: float = field(default_factory=time.monotonic)
    ingested_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    last_count: int = 0
    last_tick: float = field(default_factory=time.monotonic)

    # Latency tracking (rolling window for log output)
    _recent_latencies: list = field(default_factory=list)

    def record_ingested(self) -> None:
        self.ingested_count += 1
        IMS_SIGNALS_INGESTED_TOTAL.inc()

    def record_processed(self, latency_seconds: float = 0) -> None:
        self.processed_count += 1
        IMS_SIGNALS_PROCESSED_TOTAL.inc()
        if latency_seconds > 0:
            IMS_PROCESSING_LATENCY.observe(latency_seconds)
            self._recent_latencies.append(latency_seconds)
            # Keep only last 1000 samples for percentile logging
            if len(self._recent_latencies) > 1000:
                self._recent_latencies = self._recent_latencies[-500:]

    def record_queue_wait(self, wait_seconds: float) -> None:
        IMS_QUEUE_WAIT_TIME.observe(wait_seconds)

    def record_failed(self) -> None:
        self.failed_count += 1
        IMS_SIGNALS_FAILED_TOTAL.inc()

    def record_retry(self, worker_id: int) -> None:
        IMS_RETRY_TOTAL.labels(worker_id=str(worker_id)).inc()

    def record_db_latency(self, db_type: str, latency: float) -> None:
        IMS_DB_WRITE_LATENCY.labels(db_type=db_type).observe(latency)

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def ingestion_rate(self) -> float:
        now = time.monotonic()
        elapsed = max(now - self.last_tick, 0.001)
        rate = (self.ingested_count - self.last_count) / elapsed
        self.last_tick = now
        self.last_count = self.ingested_count
        return rate

    def latency_percentiles(self) -> dict[str, float]:
        """Calculate p50, p95, p99 from recent processing latencies."""
        if not self._recent_latencies:
            return {"p50": 0, "p95": 0, "p99": 0}
        sorted_lats = sorted(self._recent_latencies)
        n = len(sorted_lats)
        return {
            "p50": sorted_lats[int(n * 0.50)],
            "p95": sorted_lats[min(int(n * 0.95), n - 1)],
            "p99": sorted_lats[min(int(n * 0.99), n - 1)],
        }


metrics_state = MetricsState()


async def metrics_logger() -> None:
    """
    Periodic structured metrics logger — runs every 5 seconds.

    Logs throughput, queue depth, active incidents, MTTR, and latency percentiles.
    This supplements Prometheus by providing immediate visibility in container logs.
    """
    from app.services.queue import queue_depth

    while True:
        await asyncio.sleep(5)
        depth = await queue_depth()
        IMS_QUEUE_DEPTH.set(depth)
        
        # Calculate and set processing rate
        rate = metrics_state.ingestion_rate()
        IMS_PROCESSING_RATE.set(rate)

        # Update circuit breaker state gauges
        try:
            from app.services.circuit_breaker import mongo_breaker, postgres_breaker, CircuitState
            state_map = {CircuitState.CLOSED: 0, CircuitState.OPEN: 1, CircuitState.HALF_OPEN: 2}
            IMS_CIRCUIT_BREAKER_STATE.labels(dependency="mongodb").set(state_map.get(mongo_breaker.state, 0))
            IMS_CIRCUIT_BREAKER_STATE.labels(dependency="postgresql").set(state_map.get(postgres_breaker.state, 0))
        except Exception:
            pass

        async with AsyncSessionLocal() as session:
            active_result = await session.execute(
                select(func.count()).select_from(WorkItem).where(WorkItem.status != "CLOSED")
            )
            mttr_result = await session.execute(
                select(func.avg(WorkItem.mttr_minutes)).where(WorkItem.mttr_minutes != None)
            )
            active_incidents = active_result.scalar_one()
            avg_mttr = mttr_result.scalar_one() or 0

        pcts = metrics_state.latency_percentiles()
        logger.info(
            "[METRICS] Rate: %.0f sig/s | Queue: %d | Active incidents: %d | "
            "Avg MTTR: %.0f min | Latency p50=%.3fs p95=%.3fs p99=%.3fs | "
            "Processed: %d | Failed: %d",
            rate,
            depth,
            active_incidents,
            avg_mttr,
            pcts["p50"], pcts["p95"], pcts["p99"],
            metrics_state.processed_count,
            metrics_state.failed_count,
        )
