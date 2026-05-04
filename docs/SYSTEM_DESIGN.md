# System Design Document

## 1. Tech Stack Choices & Reasoning

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **API Framework** | FastAPI (Python 3.12) | Async-native ASGI framework. Native `async/await` support means the ingestion endpoint can handle thousands of concurrent connections without thread exhaustion. Pydantic v2 integration provides zero-cost payload validation. |
| **Relational DB** | PostgreSQL 17 | ACID transactions are non-negotiable for incident state transitions. Partial unique indexes (`WHERE status != 'CLOSED'`) provide database-level deduplication that is impossible in MongoDB. Row-level locking (`SELECT ... FOR UPDATE`) prevents race conditions during concurrent signal processing. |
| **Document Store** | MongoDB 7 | Raw signals are high-velocity, schema-flexible event data. MongoDB's `bulk_write` with `UpdateOne(upsert=True)` handles 10k+ writes/sec efficiently. Signals don't need relational integrity — they're append-only audit logs. |
| **Message Queue** | Redis 7 (AOF) | Sub-millisecond LPUSH latency keeps API response time under 10ms. `BRPOPLPUSH` provides atomic dequeue with crash recovery. AOF persistence ensures queued signals survive Redis restarts. Chosen over Kafka for operational simplicity at this scale. |
| **Frontend** | React + Vite | Component-based UI with WebSocket integration for real-time dashboard updates. Vite provides sub-second HMR during development. |
| **Observability** | Prometheus + Grafana | Industry standard. Pull-based scraping works naturally with containerized services. Pre-provisioned dashboards provide zero-click observability. |
| **AI/ML** | Groq (Llama 3.3 70B) | Sub-second inference via Groq's LPU hardware. `response_format=json_object` ensures structured, parseable RCA suggestions. Low temperature (0.15) provides deterministic, reproducible analysis. |

## 2. Architecture Decisions & Tradeoffs

### 2.1 Why Async Architecture

Every I/O operation in the system is async (`asyncpg`, `motor`, `redis.asyncio`). This is critical because:
- The ingestion endpoint must handle burst traffic (10k signals/sec) without blocking
- Workers perform multiple I/O operations per signal (Redis read → MongoDB write → PostgreSQL upsert)
- Synchronous I/O would require thread pools, adding latency and memory overhead

**Tradeoff**: Async code is harder to debug (stack traces are less intuitive). Mitigated by comprehensive structured logging at every stage.

### 2.2 Why Decoupled Producer-Consumer

```
API (Producer) → Redis Queue (Buffer) → Worker (Consumer) → Databases
```

The API never writes directly to PostgreSQL or MongoDB. Benefits:
- **Failure Isolation**: Database outages don't crash the API — signals queue up in Redis
- **Independent Scaling**: API nodes and workers scale independently
- **Backpressure**: Queue depth provides a natural pressure gauge

**Tradeoff**: Eventual consistency — a signal accepted by the API may take 100-200ms to appear on the dashboard. Acceptable for incident management where human response times are measured in minutes.

### 2.3 Why Dual Database (Postgres + MongoDB)

| Data | Store | Reason |
|------|-------|--------|
| Work Items, RCA, Audit Trail | PostgreSQL | Requires ACID transactions, foreign keys, partial unique indexes |
| Raw Signals, DLQ | MongoDB | High-write throughput, schema flexibility, no relational integrity needed |

**Tradeoff**: Operational complexity of managing two databases. Mitigated by Docker Compose with health checks and persistent volumes.

### 2.4 Why Redis Over Kafka

| Factor | Redis | Kafka |
|--------|-------|-------|
| Latency | Sub-millisecond | 2-5ms |
| Operational Complexity | Single binary | Zookeeper + Broker cluster |
| Throughput Ceiling | ~50k ops/sec | Millions/sec |
| Durability | AOF (good enough) | Replicated commit log (strongest) |

At our scale (10k signals/sec), Redis provides adequate durability with dramatically simpler operations. The system architecture supports swapping Redis for Kafka if throughput requirements grow beyond 50k/sec.

## 3. Scaling Strategy

### Horizontal Scaling Points

1. **API Nodes**: Stateless — scale behind a load balancer. Rate limiting uses per-IP keys, so it works across instances.
2. **Workers**: Scale with `docker-compose up --scale worker=N`. Redis queue is shared, so multiple workers drain it in parallel. Circuit breakers use Redis-backed state, ensuring distributed coordination.
3. **PostgreSQL**: Add read replicas for dashboard queries. Write load is bounded by debouncing (100 signals → 1 DB write).
4. **MongoDB**: Shard by `component_id` for write distribution.

### Bottleneck Analysis

| Component | Current Limit | Scaling Path |
|-----------|--------------|--------------|
| Redis Queue | ~50k ops/sec | Redis Cluster or Kafka migration |
| PostgreSQL Writes | ~5k txn/sec | PgBouncer + Read replicas |
| Worker Processing | 4 concurrent (configurable) | `--scale worker=10` |

## 4. Data Flow (End-to-End)

```
Signal Source → POST /api/signals
    ↓
[1] JWT Authentication (security.py)
    ↓
[2] Rate Limiting — 10k/sec per IP (slowapi)
    ↓
[3] Adaptive Throttling — check queue depth (signals.py:50-59)
    ↓
[4] LPUSH to Redis queue — returns 202 Accepted (queue.py:25-61)
    ↓
[5] Worker BRPOPLPUSH — atomic dequeue to processing list (queue.py:64-92)
    ↓
[6] Severity Classification — auto-upgrade based on component type (classifier.py)
    ↓
[7] MongoDB bulk_write — idempotent upsert on queue_id (ingestion.py:134-155)
    ↓
[8] Debounce Check — Redis Sorted Set sliding window (ingestion.py:209-258)
    ↓
[9] PostgreSQL Upsert — create/increment Work Item (ingestion.py:279-329)
    ↓
[10] Redis Pub/Sub → WebSocket broadcast → React Dashboard
```

## 5. Failure Handling Design

### 5.1 Circuit Breaker (Per-Dependency)

Located in `backend/app/services/circuit_breaker.py`. Two independent breakers:
- `mongo_breaker`: Protects MongoDB operations
- `postgres_breaker`: Protects PostgreSQL operations

State machine: `CLOSED → OPEN (after 5 failures) → HALF_OPEN (after 30s) → CLOSED (on success)`

All state is stored in Redis, making it distributed across all workers.

### 5.2 Retry Logic

Located in `backend/app/db/postgres.py:88-113`. Exponential backoff:
- Attempt 1: immediate
- Attempt 2: 150ms delay
- Attempt 3: 300ms delay
- After 3 failures: propagate exception

Only retries transient errors (`OperationalError`, `DBAPIError`). Application errors (e.g., `IntegrityError`) are not retried.

### 5.3 Dead Letter Queue

Located in `backend/app/services/ingestion.py:364-372`. Failed signals are written to MongoDB's `failed_signals` collection with:
- Original payload
- Failure reason
- Timestamp

This preserves failed data for manual investigation without blocking the processing pipeline.

### 5.4 Crash Recovery

Located in `backend/app/services/queue.py:110-130`. On worker startup:
1. Scan the `signals:processing` Redis list
2. Move all stranded messages back to `signals:queue`
3. Workers re-process them on the next iteration

Combined with idempotent MongoDB upserts (`$setOnInsert` on `queue_id`), redelivered signals are safely deduplicated.
