# Zeatop Architectural Deep-Dive

This document provides a Staff-Engineer level breakdown of the Zeatop Incident Management System, mapping the implementation to the mission-critical requirements defined in the [Engineering Assignment](../Engineering_Assignment__Incident_Management_System.pdf).

![System Architecture](../architecture_diagram/architecture_diagram.png)

---

## 1. Ingestion & Burst Resilience (The Producer)

The system is designed to handle **10,000 signals/second** without impacting service availability. This is achieved through a multi-tier backpressure and decoupling strategy:

*   **Async Decoupling (Impact)**: The API performs zero database I/O during ingestion. It executes a sub-10ms Redis `LPUSH` and returns `202 Accepted` immediately. **This ensures ingestion never blocks even during DB slowdown, preventing cascading failures under burst traffic.**
*   **Rate Limiting**: Per-IP throttling via `slowapi` prevents malicious or runaway producers from saturating the API.
*   **Adaptive Throttling**: The API monitors Redis queue depth. At **70% capacity**, it triggers a `429 Too Many Requests` with a `Retry-After` header, signaling producers to slow down before the system reaches saturation.

## 2. Intelligence & Noise Reduction (The Buffer)

A naive system would create 10,000 incidents for 10,000 signals. Zeatop implements **Distributed Debouncing**:

*   **10s Sliding Window**: Signals for the same `component_id` are grouped within a 10-second sliding window in Redis.
*   **Threshold Trigger**: Only after 100 signals arrive (or a manual override) is a formal **Work Item** created in PostgreSQL.
*   **NoSQL Linking**: All 10,000 raw signals are linked to that single Work Item in MongoDB, providing a complete audit trail without cluttering the operational database.

## 3. Polyglot Storage Strategy (The Persistence)

Zeatop uses the **"Right Tool for the Right Data"** philosophy:

*   **MongoDB (The Data Lake)**: Handles high-volume, unstructured error payloads. Used for the "Raw Signals" audit log.
*   **PostgreSQL (Source of Truth)**: Manages Work Items, State Transitions, and RCA records. Every status update is wrapped in an **ACID transaction**.
*   **Redis (The Hot-Path)**: 
    *   **Durable Queue**: Acts as the ingestion buffer.
    *   **Debounce Cache**: Prevents duplicate DB lookups during signal bursts.
    *   **Pub/Sub**: Powers real-time WebSocket updates for the UI.

## 4. Resilience Patterns (The Workflow Engine)

The system is "Safe-by-Design," implementing several mission-critical patterns:

*   **At-Least-Once Delivery**: Using the `BRPOPLPUSH` pattern, signals are never "popped" and lost. They are atomically moved to a "Processing" list and only removed once successfully persisted.
*   **Design Pattern: State Pattern**: The incident lifecycle (`OPEN` → `INVESTIGATING` → `RESOLVED` → `CLOSED`) is managed by a strict **State Machine**. This ensures consistent lifecycle management and enforces business rules (e.g., Cannot close without an RCA).
*   **Design Pattern: Strategy Pattern**: Alerting logic is decoupled. The system automatically swaps between `P0_AlertStrategy` (for RDBMS) and `P2_AlertStrategy` (for Caches) based on component classification, allowing for flexible escalation policies.
*   **Circuit Breaker**: MongoDB and PostgreSQL connections are wrapped in a **Circuit Breaker**. If a database becomes slow or unresponsive, the worker "fails fast," preventing a cascading failure of the worker pool.

## 5. Observability (The Golden Signals)

Monitoring is built-in, not bolted-on:
*   **Throughput**: `ims_signals_ingested_total` vs `ims_signals_processed_total`.
*   **Latency**: End-to-end processing time tracked in Prometheus Histograms.
*   **Saturation**: Real-time monitoring of Redis queue depth.
*   **Errors**: Dedicated counters for DLQ (Dead Letter Queue) entries and circuit breaker trips.

## 6. Conflict Resolution & Container Management

To ensure reliable operation across different environments and prevent networking "ghost" issues:

*   **Fixed Container Names**: Services like `backend`, `prometheus`, and `grafana` use fixed names to simplify external access and monitoring.
*   **Conflict Prevention**: If a build fails or you see a "Bad Gateway," it is often due to a lingering container from a previous project name (e.g., `zeatop` vs `zea`).
*   **Resolution Strategy**: Always ensure conflicting containers are removed before a major re-build:
    ```bash
    docker rm -f backend prometheus grafana
    ```
*   **Internal Isolation**: By not exposing databases (Postgres/Mongo/Redis) to the host, we prevent conflicts with local developer tools while maintaining a strict "Zero Trust" internal networking model.
