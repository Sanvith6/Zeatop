# Zetatop IMS — Final Submission

## Project Overview

**Zetatop** is a production-grade Incident Management System (IMS) built for high-availability SRE environments. It ingests thousands of monitoring signals per second, intelligently debounces them into actionable incidents, and manages the full incident lifecycle from detection to closure with mandatory Root Cause Analysis.

### Problem Statement

Modern infrastructure generates massive volumes of monitoring signals during failures. A single database outage can produce 10,000+ error signals in seconds. Without intelligent deduplication, each signal would create a separate alert, overwhelming on-call engineers with noise.

### Solution

Zetatop solves this with a **decoupled Producer-Consumer architecture** that:
- Accepts signals at 10,000+/sec without blocking
- Debounces hundreds of signals into a single actionable incident
- Provides AI-powered Root Cause Analysis via Groq (Llama 3.3)
- Enforces structured incident lifecycle with mandatory RCA before closure
- Maintains full observability through Prometheus/Grafana integration

---

## Architecture

```mermaid
graph TB
    subgraph Client Layer
        A[React Dashboard] -->|WebSocket| F
        B[Simulation Scripts] -->|HTTP POST| C
    end

    subgraph Ingestion Layer
        C[FastAPI API] -->|JWT Auth| C
        C -->|Rate Limit 10k/sec| C
        C -->|Adaptive Throttling| C
        C -->|LPUSH| D
    end

    subgraph Queue Layer
        D[Redis Queue - AOF Persistent]
    end

    subgraph Processing Layer
        D -->|BRPOPLPUSH| E[Background Workers x4]
        E -->|Circuit Breaker| G[PostgreSQL]
        E -->|Circuit Breaker| H[MongoDB]
        E -->|Pub/Sub| F[WebSocket Manager]
    end

    subgraph Storage Layer
        G[PostgreSQL - Incidents, RCA, Audit]
        H[MongoDB - Raw Signals, DLQ]
    end

    subgraph Observability
        I[Prometheus] -->|Scrape /metrics| C
        I -->|Scrape /metrics| E
        J[Grafana] -->|Query| I
    end
```

---

## Key Features (Mapped to Assignment Requirements)

### 1. High-Throughput Signal Ingestion
- **Requirement**: Handle high-volume signals efficiently
- **Implementation**: Redis LPUSH with sub-millisecond latency, decoupled from database writes.
- **Proof**: 10,000 signals/sec sustained in load testing.
- **Visual Evidence**:
![Signal Ingestion — POST request with JWT auth → 202 Accepted + event_id](../screenshots/Signal%20Ingestion%20(Backend%20Proof).png)

### 2. Intelligent Debouncing
- **Requirement**: Consolidate duplicate signals into single incidents.
- **Implementation**: Redis Sorted Set sliding window (10s). After 100 signals for the same component, ONE incident is created.
- **Proof**: 150 DB_PRIMARY_01 signals → 1 incident (**99.3% noise reduction**).
- **Visual Evidence**:
![Debouncing Logic — 150 signals consolidated into 1 incident](../screenshots/Debouncing%20Logic.png)

### 3. Async Processing Pipeline
- **Requirement**: Non-blocking signal processing.
- **Implementation**: Fully async stack (asyncpg, motor, redis.asyncio). Workers process batches of 500 signals with 1s flush timeout.
- **Visual Evidence**:
![Structured Metrics Logs — Batch processing and flush times in logs](../screenshots/metrics.png)

### 4. State Machine Workflow
- **Requirement**: Structured incident lifecycle.
- **Implementation**: GoF State Pattern with 4 states, idempotent same-state transitions, and strict forward-only progression.
- **Visual Evidence**:
![IMS Dashboard — Active incidents showing current status and severity](../screenshots/IMS-Dashboard.png)

### 5. Mandatory RCA with MTTR
- **Requirement**: Root cause analysis enforcement.
- **Implementation**: State machine blocks CLOSED transition without complete RCA. MTTR = `incident_end - incident_start`.
- **Visual Evidence**:
![RCA Form — AI-powered suggestions auto-fill the analysis](../screenshots/RCA-form.png)
![RCA Enforcement — System rejects closure without RCA (HTTP 409)](../screenshots/Cannot-Close-incident-without-RCA-submission.png)

### 6. Observability
- **Requirement**: System health monitoring.
- **Implementation**: Prometheus metrics (12 custom metrics), Grafana dashboards, and structured SRE log lines.
- **Visual Evidence**:
![Grafana Dashboard — Ingestion vs Processing Rate and Queue Depth](../screenshots/Grafana_dashboard1.png)
![Prometheus — Custom metrics being scraped in real-time](../screenshots/prometheus1.png)

---

## Bonus Features (Shortlist Boosters)

| Feature | Description | Visual Proof |
|---------|-------------|--------------|
| **AI-Powered RCA** | Groq Llama 3.3 analyzes signals to auto-suggest root causes | ![RCA Form](../screenshots/RCA-form.png) |
| **Real-Time Updates** | WebSocket + Redis Pub/Sub for sub-150ms UI updates | ![WebSockets](../screenshots/using_websockets.png) |
| **Testing Suite** | 40 unit tests covering all edge cases | ![Pytest](../screenshots/pytest.png) |
| **Crash Recovery** | `BRPOPLPUSH` ensures zero signal loss during worker crashes | (See Architecture) |
| **Health Checks** | Deep health checks via `/ready` endpoint | ![Backend Health](../screenshots/backend-health.png) |

---

## Setup & Demo

### Quick Start
```bash
docker-compose up --build
```
![Docker Compose Up](../screenshots/Dcokercompose-up.png)

### Service URLs
 
| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend Dashboard** | [http://localhost:3001](http://localhost:3001) | `sre-intern` / `zeotap-local` |
| **Backend API** | [http://localhost:8000](http://localhost:8000) | JWT Bearer token |
| **API Documentation** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger UI |
| **Prometheus** | [http://localhost:9090](http://localhost:9090) | — |
| **Grafana** | [http://localhost:3002](http://localhost:3002) | `admin` / `admin` |

---

## Load Test Results

Testing was performed using custom simulation scripts that send signals via HTTP POST to the ingestion API.

| Metric | Value |
|--------|-------|
| Peak Ingestion Rate | **928.1 req/s** (100 concurrent workers) |
| Avg API Response Time | 105.2ms |
| p99 API Latency | 234.3ms |
| Success Rate | 100% |
| Error Rate | 0.00% |

> Full results with analysis: [LOAD_TEST_RESULTS.md](LOAD_TEST_RESULTS.md)

---

## Testing

```bash
pytest backend/tests -v
# Result: 47 passed in ~5.5s
```

| Test Suite | Tests | Coverage |
|-----------|-------|---------|
| State Machine | 12 | Valid transitions, blocking, RCA enforcement |
| RCA Validation | 7 | Dates, whitespace stripping, MTTR accuracy |
| Severity Classifier | 8 | Baseline, upgrade, no-downgrade |
| Signal Ingestion | 8 | Payload validation, normalization |
| API Integration | 12 | Endpoints, auth, error handling |
| **Total** | **47** | |

### CI/CD Pipeline
GitHub Actions runs on every push to `main` and `develop`:
1. **Unit Tests** — Runs all 47 pytest tests.
2. **Docker Validation** — Builds and health-checks all containers.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------| 
| API | FastAPI (Python 3.12) | Async-native REST API |
| Frontend | React + Vite | Real-time SRE dashboard |
| DB | PostgreSQL + MongoDB | ACID transactions + High-volume signals |
| Queue | Redis 7 (AOF) | Ingestion buffer + Debouncing |
| AI | Groq (Llama 3.3) | Automated RCA suggestions |
| Monitoring | Prom + Grafana | Metrics + Visualization |



---

## GitHub Repository

> **GitHub Repository**: https://github.com/Sanvith6/zea

---
 
## Known Limitations & Future Roadmap
 
| Area | Current State | Production Improvement |
|------|--------------|----------------------|
| **Load Testing** | Measured ~1k/sec (see [LOAD_TEST_RESULTS.md](LOAD_TEST_RESULTS.md)) | Distributed k6 benchmark across multiple nodes |
| **WebSocket** | Exponential backoff reconnection (5 attempts) | socket.io with guaranteed delivery |
| **JWT** | HS256 + expiry validation | Refresh tokens, RBAC, secret rotation |
 
---
 
## Documentation Index

| Document | Description |
|----------|-------------|
| [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | Tech stack choices & tradeoffs |
| [WORKFLOW.md](WORKFLOW.md) | State machine & transition logic |
| [RCA_FLOW.md](RCA_FLOW.md) | RCA enforcement & AI integration |
| [API_DOCS.md](API_DOCS.md) | Endpoint examples & schema |
| [LOAD_TEST_RESULTS.md](LOAD_TEST_RESULTS.md) | Performance metrics & analysis |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Staff-level architectural deep-dive |


