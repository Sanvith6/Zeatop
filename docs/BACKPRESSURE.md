# Backpressure Strategy

## Overview

Backpressure is the system's ability to gracefully degrade under load instead of crashing. Zeatop implements a **four-tier backpressure strategy** that progressively restricts ingestion as the system approaches capacity.

---

## 1. The Four Tiers

```
Queue Depth:  0%                    50%                 70%                80%               100%
              ├─────────────────────┼───────────────────┼──────────────────┼─────────────────┤
              │   NORMAL            │   WARNING         │  THROTTLING      │  CRITICAL       │ REJECTION
              │   Full throughput   │   Log warnings    │  HTTP 429        │  Log critical   │ HTTP 503
              │                     │                   │  Retry-After: 5  │                 │
```

### Tier 1: Normal Operation (0–50% queue)

- Full throughput, no restrictions
- Signals are accepted and LPUSHed to Redis in <10ms
- Workers drain the queue at full capacity

### Tier 2: Warning State (50–70% queue)

- **What happens**: Warning-level log messages are emitted every time a signal is enqueued
- **Why**: Gives operators early warning that ingestion is outpacing processing
- **Action needed**: Consider scaling workers (`docker-compose up --scale worker=N`)

**File**: `backend/app/services/queue.py:39-53`
```python
warn_level = int(settings.queue_max_size * settings.queue_warn_threshold)
critical_level = int(settings.queue_max_size * settings.queue_critical_threshold)

if depth >= critical_level:
    logger.critical("Queue depth CRITICAL: %d/%d (%.0f%%)", ...)
elif depth >= warn_level:
    logger.warning("Queue depth elevated: %d/%d (%.0f%%)", ...)
```

### Tier 3: Adaptive Throttling (70%+ queue)

- **What happens**: API returns `HTTP 429 Too Many Requests` with `Retry-After: 5` header
- **Why**: Gives upstream producers a soft signal to slow down before the hard cliff of rejection
- **Effect**: Well-behaved clients will backoff and retry, reducing ingestion pressure

**File**: `backend/app/routers/signals.py:44-59`
```python
depth = await queue_depth()
throttle_threshold = int(settings.queue_max_size * settings.adaptive_throttle_threshold)

if depth >= throttle_threshold:
    pressure_pct = (depth / settings.queue_max_size) * 100
    raise HTTPException(
        status_code=429,
        detail=f"Adaptive throttling active — queue at {pressure_pct:.0f}% capacity.",
        headers={"Retry-After": "5"},
    )
```

### Tier 4: Rejection (100% queue)

- **What happens**: API returns `HTTP 503 Service Unavailable`
- **Why**: The queue is full — accepting more signals would risk Redis OOM
- **Redis config**: `maxmemory-policy noeviction` ensures Redis rejects new writes rather than silently evicting queued signals

**File**: `backend/app/services/queue.py:42-43`
```python
if depth >= settings.queue_max_size:
    raise QueueFullError("Ingestion queue is saturated; retry shortly")
```

---

## 2. Configuration

All thresholds are configurable via environment variables without code changes:

| Variable | Default | Purpose |
|----------|---------|---------|
| `QUEUE_MAX_SIZE` | 10000 | Maximum signals in the Redis queue |
| `QUEUE_WARN_THRESHOLD` | 0.5 | Log warnings at 50% capacity |
| `QUEUE_CRITICAL_THRESHOLD` | 0.8 | Log critical at 80% capacity |
| `ADAPTIVE_THROTTLE_THRESHOLD` | 0.7 | Return 429 at 70% capacity |

**File**: `backend/app/config.py:42-47`

---

## 3. What Happens When Databases Are Slow

### Scenario: PostgreSQL Latency Spike

1. Workers slow down (each signal takes longer to process)
2. Queue depth increases because ingestion continues at full speed
3. At 50% → warning logs alert operators
4. At 70% → adaptive throttling starts returning 429
5. At 100% → hard rejection with 503

Meanwhile:
- The **Circuit Breaker** monitors PostgreSQL failures independently
- After 5 consecutive failures, it trips to `OPEN` state
- Workers stop attempting PostgreSQL writes for 30 seconds (recovery timeout)
- Signals are routed to the **Dead Letter Queue** (MongoDB `failed_signals` collection)
- The API continues accepting signals into Redis (decoupled architecture)

### Scenario: Redis Memory Pressure

Redis is configured with:
```yaml
command: ["redis-server", "--appendonly", "yes", "--maxmemory", "256mb", "--maxmemory-policy", "noeviction"]
```

- `noeviction`: Redis will never silently drop queued messages
- When Redis reaches 256MB, new LPUSH operations fail
- The `enqueue_signal()` function catches this and raises `QueueFullError`
- The API returns 503, signaling upstream producers to back off

---

## 4. Retry Logic (Worker Side)

When a worker encounters a transient database error:

**File**: `backend/app/db/postgres.py:88-113`

```
Attempt 1: Execute immediately
    ↓ (fail → transient error?)
Attempt 2: Wait 150ms, retry
    ↓ (fail → transient error?)
Attempt 3: Wait 300ms, retry
    ↓ (fail)
Propagate exception → Circuit breaker records failure
```

Key design decisions:
- Only `OperationalError` and `DBAPIError` are retried (transient network/connection issues)
- `IntegrityError` is NOT retried (application logic error, not transient)
- Exponential backoff prevents thundering herd on recovery
- Each retry is recorded as a Prometheus metric (`ims_retry_total`)

---

## 5. Batch Processing (Worker Optimization)

**File**: `backend/app/services/ingestion.py:30-45`

Workers don't process signals one-at-a-time. They use a `BatchBuffer` that flushes when:
- Buffer reaches 500 signals (`worker_batch_size`), OR
- 1 second has elapsed since last flush (`worker_batch_timeout`)

Benefits:
- MongoDB `bulk_write` reduces round-trips (500 individual writes → 1 bulk operation)
- Redis `pipeline` for bulk acknowledgment
- Amortizes connection overhead across hundreds of signals

---

## 6. End-to-End Pressure Flow

```
                                    ┌─────────────────┐
                                    │   Monitoring     │
                                    │   Agents         │
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │   Rate Limiter   │ ← 10k/sec per IP
                                    │   (slowapi)      │
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │   Adaptive       │ ← 429 at 70% queue
                                    │   Throttling     │
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │   Redis Queue    │ ← 503 at 100% queue
                                    │   (bounded)      │ ← noeviction policy
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │   Worker Pool    │ ← Batch processing
                                    │   (4 concurrent) │ ← Circuit breakers
                                    └────────┬────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              │              │              │
                     ┌────────▼──────┐ ┌─────▼──────┐ ┌────▼────────┐
                     │  PostgreSQL   │ │  MongoDB   │ │  DLQ        │
                     │  (incidents)  │ │  (signals) │ │  (failures) │
                     └───────────────┘ └────────────┘ └─────────────┘
```
