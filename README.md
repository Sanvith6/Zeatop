# Incident Management System

Production-grade Incident Management System built with FastAPI, React, PostgreSQL, MongoDB, Redis, and Docker Compose. Designed around SRE principles: resilient ingestion, signal debouncing, strict incident lifecycle, and full observability.

> **Designed with a failure-first mindset**: ingestion remains available even when downstream systems fail.

## Architecture

```
┌──────────────┐     ┌──────────────────────────────────────┐
│  React SPA   │────▶│  FastAPI Backend                     │
│  Dashboard   │     │  • JWT Auth                          │
└──────────────┘     │  • Rate Limiting (slowapi)           │
                     │  • Adaptive Throttling (70% queue)   │
┌──────────────┐     │  • Pydantic Validation               │
│  Simulation  │────▶│  • Returns 202 + event_id            │
│  Script      │     └───────────────┬──────────────────────┘
└──────────────┘                     │ LPUSH
                                     ▼
                     ┌──────────────────────────────────────┐
                     │  Redis (AOF persistent)              │
                     │  • Ingestion Queue (signals:queue)   │
                     │  • Processing List (crash recovery)  │
                     │  • Debounce Cache (sorted sets)      │
                     │  • Dashboard Cache (10s TTL)         │
                     └───────────────┬──────────────────────┘
                                     │ BRPOPLPUSH
                                     ▼
                     ┌──────────────────────────────────────┐
                     │  Worker Container (separate process) │
                     │  • Circuit Breaker (per dependency)  │
                     │  • Severity Auto-Classification      │
                     │  • Idempotent Processing             │
                     │  • Retry (3x exponential backoff)    │
                     │  • Dead Letter Queue (MongoDB)       │
                     └──────┬───────────────┬───────────────┘
                            │               │
                            ▼               ▼
                     ┌─────────────┐ ┌─────────────┐
                     │  MongoDB    │ │ PostgreSQL  │
                     │  Raw signals│ │ Work items  │
                     │  DLQ        │ │ RCA + MTTR  │
                     └─────────────┘ └─────────────┘
```

For a detailed architecture deep-dive, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup

```bash
docker-compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3001 |
| Backend API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3002 |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |

**Demo credentials:** `sre-intern` / `zeotap-local` (Grafana: `admin` / `Sanvith@123`)

> [!TIP]
> **Observability Stack**: Metrics are scraped by Prometheus and visualized in Grafana using pre-provisioned dashboards.

## Core Reliability Patterns

### 1. Delivery & Idempotency (Correctness)
**The system guarantees at-least-once delivery.** 
By using Redis `BRPOPLPUSH`, signals are never lost if a worker crashes mid-processing. Any redelivered signals are handled **idempotently** via:
- **MongoDB**: Upsert on `event_id` prevents duplicate signal records.
- **PostgreSQL**: Partial unique index on active work items prevents duplicate incident creation.
- **Side Effects**: Deduplication logic ensures alerts are only fired once per incident.

## System Guarantees
- **At-least-once delivery**: Via Redis durable queue (`BRPOPLPUSH` pattern).
- **Idempotent processing**: Prevents duplicate incidents even if signals are redelivered.
- **Eventual consistency**: Between raw signals (MongoDB) and work items (Postgres).

## Backpressure Strategy
- **<50% queue**: Normal operations.
- **50–70% queue**: Warning state (latency tracking).
- **>70% queue**: Adaptive throttling (HTTP 429).
- **100% queue**: Rejection (HTTP 503) to protect system stability.

## Example Incident Investigation
A spike in database errors triggered multiple P0 incidents across components. 
Using raw signals in MongoDB and Prometheus metrics, we traced the root cause to connection timeouts. 
The **Circuit Breaker** automatically prevented cascading failures, keeping the ingestion API healthy while the investigation and recovery continued.

### 2. Failure Walkthrough: PostgreSQL Outage
This scenario demonstrates the system's resilience under dependency failure:
1. **Detection**: Worker attempts a write to PostgreSQL; it fails with a connection error.
2. **Backoff**: The worker retries 3 times with exponential backoff (0.2s, 0.4s, 0.8s).
3. **Resilience**: After 5 consecutive failures, the **Circuit Breaker** trips to `OPEN` state.
4. **Safety**: Subsequent signals fail-fast and are routed to the **Dead Letter Queue (MongoDB)**.
5. **Ingestion**: The API continues to accept signals into the Redis queue, decoupled from the DB outage.
6. **Recovery**: Once Postgres returns, the breaker transitions to `HALF_OPEN`, probes the DB, and resumes normal processing.

### 3. Scaling Story
The system is designed for **horizontal scalability**:
- **Ingestion**: API nodes can be scaled behind a load balancer to handle 10k+ requests/sec.
- **Processing**: Worker containers can be scaled independently (`--scale worker=10`) to drain the queue faster during high-burst events.
- **Decoupling**: The Redis queue acts as a buffer, preventing bursty traffic from overwhelming downstream databases.

### 4. Engineering Tradeoffs & Limitations
- **Redis vs Kafka**: We use Redis for its simplicity and sub-millisecond latency. At extreme scales (100k+ signals/sec), Kafka would be a superior choice for durability and partitioned consumption.
- **Consistency**: We prioritize **Eventual Consistency**. A signal is captured immediately, but its associated incident may appear on the dashboard 1-2 seconds later. This is a deliberate tradeoff to maintain high ingestion throughput.

## SRE Focus

| Concern | Implementation |
| --- | --- |
| **Backpressure** | Three-tier: normal → adaptive throttling (429) → rejection (503) |
| **Circuit Breaker** | Per-dependency (Mongo/Postgres) isolation |
| **Alert Noise** | Debounce window (100+ signals/10s) creates ONE incident |
| **Closure Control** | State machine blocks `CLOSED` without a complete RCA |
| **Observability** | Prometheus metrics + 5-second interval structured latency logs |

---

## 📄 PDF Submission Checklist
1. **GitHub Link**: Clearly visible at the top.
2. **Architecture**: Use the ASCII diagram above or a screenshot of `docs/ARCHITECTURE.md`.
3. **Screenshots**: Include the Dashboard with stats cards and the `/metrics` endpoint.
4. **Resilience**: Mention the **PostgreSQL Outage walkthrough**.
5. **Testing**: Mention **43 unit tests passing**.
