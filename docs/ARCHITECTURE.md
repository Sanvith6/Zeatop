# Zetatop IMS — Architecture Deep Dive

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                │
│  ┌───────────────┐  ┌───────────────────┐  ┌────────────────────┐  │
│  │  React SPA    │  │  Simulation Script │  │  Load Test Script  │  │
│  │  Dashboard    │  │  (simulate_failure)│  │  (load_test.py)    │  │
│  └──────┬────────┘  └────────┬──────────┘  └────────┬───────────┘  │
└─────────┼────────────────────┼──────────────────────┼──────────────┘
          │ HTTP               │ HTTP                  │ HTTP
          ▼                    ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      INGESTION LAYER (FastAPI)                      │
│                                                                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ JWT Auth │→ │Rate Limit │→ │   Adaptive   │→ │  Redis Queue │  │
│  │          │  │ (slowapi)  │  │  Throttling  │  │   (LPUSH)    │  │
│  └──────────┘  └───────────┘  └──────────────┘  └──────────────┘  │
│                                                                     │
│  Returns: 202 Accepted + event_id                                   │
│           429 Too Many Requests (adaptive throttling at 70%)        │
│           503 Service Unavailable (queue full at 100%)              │
└─────────────────────────────────────────────────────────────────────┘
          │
          │ Redis LPUSH
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      QUEUE LAYER (Redis)                            │
│                                                                     │
│  signals:queue ──BRPOPLPUSH──▶ signals:processing                   │
│                                                                     │
│  • AOF persistence (--appendonly yes)                               │
│  • noeviction policy (never silently drop messages)                 │
│  • Persistent volume (survives container restarts)                  │
└─────────────────────────────────────────────────────────────────────┘
          │
          │ BRPOPLPUSH (crash-safe dequeue)
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     WORKER LAYER (Separate Container)               │
│                                                                     │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │ Dequeue    │→ │ Circuit      │→ │ Process Signal            │   │
│  │ Signal     │  │ Breaker      │  │  1. Upsert to MongoDB     │   │
│  │            │  │ (per-dep)    │  │  2. Classify severity     │   │
│  └────────────┘  └──────────────┘  │  3. Debounce check        │   │
│                                     │  4. Create/update WorkItem│   │
│  ┌────────────┐  ┌──────────────┐  │  5. Fire alert webhook    │   │
│  │ Retry      │  │ Dead Letter  │  └──────────────────────────┘   │
│  │ (exp. back │  │ Queue (DLQ)  │                                  │
│  │  off, 3x)  │  │ (MongoDB)    │  Workers: configurable pool     │
│  └────────────┘  └──────────────┘  (WORKER_CONCURRENCY=4)         │
└─────────────────────────────────────────────────────────────────────┘
          │                    │
          ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│  MongoDB         │  │  PostgreSQL      │
│  (Raw Signals)   │  │  (Work Items)    │
│                  │  │                  │
│  • Append-only   │  │  • ACID txns     │
│  • Schema-free   │  │  • Row locking   │
│  • Indexed on:   │  │  • Partial unique│
│    component_id  │  │    index (dedup) │
│    timestamp     │  │  • FK integrity  │
│    queue_id (uniq│  │  • Status + sev  │
│    work_item_id  │  │    indexes       │
└──────────────────┘  └──────────────────┘
```

## Data Flow: Lifecycle of a Signal

### 1. Ingestion (< 5ms)
A signal hits `POST /api/signals`. The API:
- Authenticates via JWT
- Rate-limits per-IP (configurable, default 10k/sec)
- Checks queue depth for adaptive throttling (429 at 70%)
- Validates payload via Pydantic
- Pushes to Redis queue via LPUSH
- Returns `202 Accepted` with `event_id`

### 2. Queuing (< 1ms)
The signal sits in `signals:queue` until a worker picks it up.
Redis AOF ensures the signal survives restarts.

### 3. Processing (10-100ms)
A worker atomically pops the signal via BRPOPLPUSH:
- **MongoDB upsert**: Idempotent write keyed on `queue_id` (dedup)
- **Severity classification**: Auto-upgrade based on component blast radius
- **Debounce check**: Count signals in 10-second window via Redis sorted set
- **Work item resolution**: Create new or link to existing PostgreSQL work item
- **Alert dispatch**: Fire webhook via strategy pattern

### 4. Resolution (human-driven)
SRE operators use the React dashboard to:
- Transition state: OPEN → INVESTIGATING → RESOLVED → CLOSED
- Submit Root Cause Analysis (required before closing)
- Review MTTR metrics

## Design Decisions

### Why MongoDB + PostgreSQL (not just one)?

| Concern | MongoDB | PostgreSQL |
|---------|---------|------------|
| Raw signal storage | ✅ Schema-free, append-optimized | ❌ Would bloat WAL, slow VACUUM |
| Work item state | ❌ No true multi-doc transactions | ✅ ACID transactions, row locking |
| Deduplication | ❌ No partial unique indexes | ✅ Partial unique index on active items |
| Query patterns | Time-range scans, flexible schemas | Relational joins, aggregations |

### Why Redis (not Kafka)?

Redis is the right choice for this scale:
- Already in the stack (cache + debounce + queue = one dependency)
- Sub-millisecond latency
- AOF persistence provides durability
- Simple operational model

**When to upgrade to Kafka**: Sustained 10k+ signals/sec, need for partitioned
consumption, multi-datacenter replication, or consumer group management.

### Consistency Model

The system accepts **eventual consistency** between MongoDB and PostgreSQL.
A signal may exist in MongoDB briefly before its work item is created in
PostgreSQL. This is intentional:
- We prioritize signal capture (no data loss) over instant consistency
- The debounce window naturally introduces a delay
- Work items are created within seconds of threshold being reached

## Delivery Guarantees

**At-least-once delivery** via BRPOPLPUSH pattern:

```
signals:queue  →  BRPOPLPUSH  →  signals:processing
success        →  LREM (ack)
crash          →  item stays in processing → recovered on restart
```

**Idempotency** ensures correctness under redelivery:
- MongoDB upsert on `queue_id` prevents duplicate signal inserts
- PostgreSQL partial unique index prevents duplicate active work items
- `if existing_work_item_id: return` prevents double-linking

Combined: at-least-once + idempotency = **effectively exactly-once processing**.

## Failure Scenarios

| Failure | Impact | Recovery |
|---------|--------|----------|
| **API crash** | New signals rejected | `restart: unless-stopped` restarts container; queued signals safe in Redis |
| **Worker crash** | Processing pauses | Restart recovers stranded signals from processing queue |
| **Redis crash** | Queue lost if no AOF | AOF + persistent volume preserves queue; cache rebuilt lazily |
| **PostgreSQL down** | Work items can't be created | Circuit breaker opens → signals routed to DLQ → replayed after recovery |
| **MongoDB down** | Raw signals can't be stored | Circuit breaker opens → signals routed to DLQ |
| **Network partition** | Varies by component | Timeouts (5s) prevent hanging; retries handle transient failures |
| **Queue saturation** | New signals rejected (503) | Upstream producers retry with backoff; workers drain the backlog |
| **Burst traffic** | Adaptive throttling (429) | Signals queued at 70% → rejected at 100% → 503 backpressure |

## System Limits

| Metric | Tested Value | Bottleneck |
|--------|-------------|------------|
| Max signals/sec (ingestion) | ~1,000/sec sustained | API event loop + Redis LPUSH |
| Queue capacity | 10,000 signals | Configurable via QUEUE_MAX_SIZE |
| Processing latency | p95 < 100ms | MongoDB + PostgreSQL write |
| Worker concurrency | 4 tasks/container | Configurable, scales horizontally |
| Dashboard refresh | 5 second polling | Redis cache TTL |

## Tradeoffs

| Decision | Benefit | Cost |
|----------|---------|------|
| Redis over Kafka | Simple ops, sub-ms latency | Single-threaded bottleneck at 50k+ ops/sec |
| Eventual consistency | High throughput, simple code | Brief delay between signal and work item |
| Separate worker container | Independent scaling, fault isolation | Shared codebase, extra container |
| Application circuit breaker | Simple, no external dependency | Not distributed across worker replicas |
| Rule-based classifier | Deterministic, auditable | Cannot learn from historical patterns |
