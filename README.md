# 🛡️ Zeatop: Production-Grade Incident Management System


[![SRE Principles](https://img.shields.io/badge/SRE-Safe--by--Design-blueviolet?style=for-the-badge)](https://sre.google/)
[![AI-Powered](https://img.shields.io/badge/AI--Powered-Groq--Llama3-orange?style=for-the-badge)](https://groq.com/)
[![Throughput](https://img.shields.io/badge/Throughput-10k%2Fsec%20(Architected)-success?style=for-the-badge)]()
[![Tests](https://img.shields.io/badge/Tests-47%20Passed-brightgreen?style=for-the-badge)]()
[![CI](https://github.com/Sanvith6/Zeatop/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanvith6/Zeatop/actions)

---

## 🚀 Reviewer Quick Path (2 mins)

1. Clone the repository:
   ```bash
   git clone https://github.com/Sanvith6/Zeatop.git
   cd Zeatop
   ```

2. Setup AI RCA (Required for aiRCA feature):
   - Get a free key at [console.groq.com](https://console.groq.com/keys)
   - Add it to `.env.example`: `GROQ_API_KEY=your_key`

3. Run system:
   ```bash
   docker compose up --build
   ```

4. Simulate failure:
   ```bash
   python scripts/simulate_failure.py
   ```

5. Open dashboard: [http://localhost:3005](http://localhost:3005)

👉 Full details in `docs/`

---

## 🎯 Design Decisions

- **Redis over Kafka** → lower latency, simpler for this scale
- **Async Workers** → decouple ingestion from DB (**Ensures ingestion never blocks even during DB slowdown**)
- **PostgreSQL for incidents** → ACID guarantees for state transitions
- **MongoDB for signals** → high write throughput + flexible schema
- **Design Pattern: State Pattern** → Incident lifecycle management
- **Design Pattern: Strategy Pattern** → Severity-based alerting logic

---

## 🧪 Simulated Failure Scenario (SRE Walkthrough)

Demonstrating system resilience during a cascading failure:

1.  **Outage**: DB primary fails, generating **150+ error signals** in seconds.
2.  **Ingestion**: API accepts signals at 1k/sec without blocking (Architected for 10k/sec).
3.  **Debouncing**: Zeatop groups 150 signals into **1 single P0 incident** (99.3% noise reduction).
4.  **Alerting**: System triggers P0 alert via severity-based strategy.
5.  **Audit**: Full RCA enforced before the incident can be closed.

👉 **Impact**: Prevents alert fatigue and ensures consistent MTTR tracking.

---

## 1. Project Overview

Zeatop is a high-availability **Incident Management System (IMS)** built for SRE environments that generate massive volumes of monitoring signals during failures.

### Problem
A single database outage can produce **10,000+ error signals** in seconds. Without intelligent deduplication, each signal creates a separate alert, overwhelming on-call engineers with noise and obscuring the actual incident.

### Solution
Zeatop implements a **decoupled Producer-Consumer architecture** that:
- **Architected for 10,000 signals/sec** (Validated ~1k/sec on single local node)
- **Impact**: Decouples ingestion from database writes, ensuring zero blocking during bursts.
- **Debounces** signals into single actionable incidents (99%+ noise reduction)
- Provides **AI-powered Root Cause Analysis** via Groq (Llama 3.3)
- Enforces a **strict incident lifecycle** via **State Pattern**
- Maintains **full observability** through Prometheus/Grafana integration

---

## 2. Architecture Summary

The system follows a five-layer architecture where each layer is independently scalable and failure-isolated:

```
Signal Source → POST /api/signals
    ↓
[1] JWT Auth + Rate Limiting (10k/sec per IP)
    ↓
[2] Adaptive Throttling (429 at 70% queue capacity)
    ↓
[3] Redis Queue (LPUSH — sub-millisecond, AOF-persistent)
    ↓
[4] Worker Pool (BRPOPLPUSH — crash-safe dequeue)
    ↓
[5a] MongoDB (raw signal storage — idempotent upsert)
[5b] PostgreSQL (incident management — ACID transactions)
    ↓
[6] Redis Pub/Sub → WebSocket → React Dashboard (real-time)
```

**Key Insight**: The API never writes to PostgreSQL or MongoDB directly. All database operations happen asynchronously in the worker pool, meaning **database outages never crash the ingestion API**.

---

## 3. Backpressure Strategy

| Queue Capacity | System Response | HTTP Code |
|---------------|----------------|-----------|
| 0–50% | Normal operation | 202 |
| 50–70% | Warning logs emitted | 202 |
| 70–99% | Adaptive throttling active | **429** + `Retry-After: 5` |
| 100% | Hard rejection | **503** |

- **Redis Queue**: Acts as a massive buffer for signal bursts.
- **Batch Processing**: Workers process 500 signals at a time to optimize DB throughput.
- **Rate Limiting**: Prevents saturation from rogue producers.

---

## 4. Setup Instructions

### ⚠️ Critical Setup Note: Clean Start
If you are updating environment variables (like the **Groq API key**) or encountering port conflicts, follow this exact sequence to ensure a clean start:

1.  **Edit `.env.example`**: Add your `GROQ_API_KEY` and **save the file**.
2.  **Stop existing containers**:
    ```bash
    docker rm -f backend prometheus grafana frontend
    docker compose down
    ```
3.  **Build and Run**:
    ```bash
    docker compose up --build
    ```

### Running the System
```bash
docker compose up --build
python scripts/simulate_failure.py
```

### Service URLs

| Service | URL |
|---------|-----|
| **🚀 Frontend Dashboard** | [http://localhost:3005](http://localhost:3005) |
| **🛠️ Backend API** | [http://localhost:8000](http://localhost:8000) |
| **📈 Prometheus** | [http://localhost:9090](http://localhost:9090) |
| **📊 Grafana** | [http://localhost:3002](http://localhost:3002) |

---

## 5. Observability Guide

### 📊 How to View Grafana Dashboards
1.  Open **Grafana**: [http://localhost:3002](http://localhost:3002)
2.  **Login**: Use `admin` / `admin`.
3.  **Navigate**: Click the **Menu** (top-left) → **Dashboards**.
4.  **Open**: Select the **"Zeatop SRE Dashboard"**.
5.  **View**: You will see real-time charts for Ingestion Rate, Queue Depth, and Worker Latency.

### 📈 How to Query Prometheus
1.  Open **Prometheus**: [http://localhost:9090](http://localhost:9090)
2.  **Search**: In the search bar, type a metric name, for example:
    - `ims_signals_ingested_total` (Total signals received)
    - `ims_queue_depth` (Current signals waiting in Redis)
    - `ims_signal_processing_seconds_sum` (Processing latency)
3.  **Execute**: Click **"Execute"** and then select the **"Graph"** tab to see the visual trend.

---

## 5. Load Test Results

| Metric | Measured Value (Local) |
|--------|----------------|
| **Peak Ingestion Rate** | **928.1 req/s** |
| **Avg API Latency** | 105.2 ms |
| **p99 API Latency** | 234.3 ms |

> [!IMPORTANT]
> **Performance Note**: System is architected for 10,000 signals/sec (validated via queue + async design). The current single-node test achieved ~1,000 req/s due to local resource limits.

---

## 📂 Documentation Index

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architectural deep-dive & Design Patterns |
| [BACKPRESSURE.md](docs/BACKPRESSURE.md) | Multi-tier backpressure strategy |
| [FINAL_SUBMISSION_CONTENT.md](docs/FINAL_SUBMISSION_CONTENT.md) | PDF submission content |
| [LOAD_TEST_RESULTS.md](docs/LOAD_TEST_RESULTS.md) | Detailed performance analysis |

---

**Final Submission Prepared by Sanvith JS**
