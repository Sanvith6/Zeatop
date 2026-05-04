# API Documentation

All endpoints require JWT Bearer authentication unless noted otherwise. Obtain a token via `POST /api/auth/token`.

---

## Authentication

### `POST /api/auth/token` — Issue JWT Token

**File**: `backend/app/routers/auth.py`

| Field | Value |
|-------|-------|
| Auth Required | No |
| Rate Limited | No |

**Request Body**:
```json
{
  "username": "sre-intern",
  "password": "zeotap-local"
}
```

**Response** (200):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Error** (401):
```json
{
  "detail": "Invalid username or password"
}
```

---

## Signal Ingestion

### `POST /api/signals` — Ingest a Monitoring Signal

**File**: `backend/app/routers/signals.py`

| Field | Value |
|-------|-------|
| Auth Required | Yes (Bearer JWT) |
| Rate Limited | Yes (10,000/second per IP) |
| Response Code | 202 Accepted |

**Request Body**:
```json
{
  "component_id": "DB_PRIMARY_01",
  "component_type": "rdbms",
  "error_message": "Primary database connection timeout",
  "severity": "P0",
  "timestamp": "2026-05-04T10:30:00Z"
}
```

**Valid `component_type` values**: `cache`, `rdbms`, `api`, `queue`, `nosql`, `mcp`, `external`, `compute`, `storage`

**Valid `severity` values**: `P0`, `P1`, `P2`, `P3`

**Response** (202):
```json
{
  "status": "accepted",
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Error Responses**:
| Code | Condition | Body |
|------|-----------|------|
| 422 | Invalid payload (wrong enum, missing field) | Pydantic validation errors |
| 429 | Queue at 70%+ capacity (adaptive throttling) | `{"detail": "Adaptive throttling active — queue at 75% capacity. Retry shortly."}` |
| 503 | Queue at 100% capacity | `{"detail": "Ingestion queue is saturated; retry shortly"}` |

---

## Work Items (Incidents)

### `GET /api/workitems` — List Active Incidents

**File**: `backend/app/routers/workitems.py`

| Field | Value |
|-------|-------|
| Auth Required | Yes |
| Cache | Redis (10s TTL) |

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | `null` | Filter by status. Use `CLOSED` for history. |

**Response** (200):
```json
[
  {
    "id": "cc9a6503-7d57-47cc-897f-dff0a8864282",
    "component_id": "DB_PRIMARY_01",
    "component_type": "rdbms",
    "severity": "P0",
    "status": "OPEN",
    "signal_count": 150,
    "created_at": "2026-05-04T10:30:00",
    "updated_at": "2026-05-04T10:31:00",
    "rca_id": null,
    "mttr_minutes": null
  }
]
```

### `GET /api/workitems/{id}` — Incident Detail

**Response** (200): Same as list item, plus:
```json
{
  "signals": [
    {
      "_id": "664f...",
      "component_id": "DB_PRIMARY_01",
      "component_type": "rdbms",
      "error_message": "Primary database connection timeout",
      "severity": "P0",
      "timestamp": "2026-05-04T10:30:00"
    }
  ],
  "timeline": [
    {
      "from_status": null,
      "to_status": "OPEN",
      "changed_at": "2026-05-04T10:30:00"
    }
  ],
  "rca": null
}
```

### `PATCH /api/workitems/{id}/transition` — Transition Incident State

**Request Body**:
```json
{
  "new_state": "INVESTIGATING"
}
```

**Valid transitions**: `OPEN→INVESTIGATING`, `INVESTIGATING→RESOLVED`, `RESOLVED→CLOSED` (requires RCA)

**Response** (200): Updated work item object

**Error** (409):
```json
{
  "detail": "Cannot transition from OPEN to CLOSED"
}
```

### `POST /api/workitems/{id}/rca` — Submit Root Cause Analysis

**Request Body**:
```json
{
  "incident_start": "2026-05-04T10:00:00Z",
  "incident_end": "2026-05-04T10:22:00Z",
  "root_cause_category": "Infrastructure",
  "fix_applied": "Restarted the primary database node and increased connection pool size",
  "prevention_steps": "Add automated failover, implement connection pooling with PgBouncer"
}
```

**Valid `root_cause_category` values**: `Infrastructure`, `Code Deployment`, `Configuration Change`, `External Dependency`, `Unknown`

**Response** (200):
```json
{
  "id": "f1e2d3c4-b5a6-7890-abcd-ef1234567890",
  "work_item_id": "cc9a6503-7d57-47cc-897f-dff0a8864282",
  "incident_start": "2026-05-04T10:00:00",
  "incident_end": "2026-05-04T10:22:00",
  "root_cause_category": "Infrastructure",
  "fix_applied": "Restarted the primary database node...",
  "prevention_steps": "Add automated failover...",
  "submitted_at": "2026-05-04T10:35:00",
  "mttr_minutes": 22.0
}
```

### `POST /api/workitems/{id}/suggest-rca` — AI-Powered RCA Suggestion

**Request Body**: None

**Response** (200):
```json
{
  "root_cause_category": "Infrastructure",
  "fix_applied": "Restarting the database service and checking network connectivity to resolve the connection timeout",
  "prevention_steps": "Implement database connection pooling, configure retry logic, and monitor database server resource utilization to prevent timeouts"
}
```

---

## Analytics

### `GET /api/analytics/signals/timeseries` — Signal Throughput Over Time

**Query Parameters**: `minutes` (int, default: 60)

**Response** (200):
```json
[
  {"time": "2026-05-04T10:30:00Z", "count": 150},
  {"time": "2026-05-04T10:31:00Z", "count": 80}
]
```

### `GET /api/analytics/incidents/distribution` — Incident Distribution

**Response** (200):
```json
{
  "by_severity": {"P0": 2, "P1": 1, "P2": 3},
  "by_type": {"rdbms": 1, "cache": 2, "mcp": 1}
}
```

### `GET /api/analytics/mttr/history` — MTTR Trends

**Response** (200):
```json
[
  {"day": "2026-05-03", "avg_mttr": 22.5},
  {"day": "2026-05-04", "avg_mttr": 15.0}
]
```

---

## System Endpoints

### `GET /health` — Liveness Check

**Auth Required**: No

```json
{"status": "ok", "uptime": 3600}
```

### `GET /ready` — Readiness Check (All Dependencies)

**Auth Required**: No

```json
{
  "status": "ready",
  "uptime": 3600,
  "queue_depth": 0,
  "dependencies": {
    "postgres": "ok",
    "mongo": "ok",
    "redis": "ok"
  }
}
```

### `GET /metrics` — Prometheus Metrics

**Auth Required**: No

Returns Prometheus-format text with all system metrics (see Observability section).

### `WebSocket /ws/incidents` — Real-Time Incident Updates

**Auth Required**: No

Receives JSON messages whenever incidents are created, updated, or transitioned:
```json
{"type": "INCIDENT_CREATED", "work_item_id": "cc9a6503..."}
{"type": "INCIDENT_UPDATED", "work_item_id": "cc9a6503..."}
{"type": "INCIDENT_TRANSITIONED", "work_item_id": "cc9a6503...", "new_state": "INVESTIGATING"}
{"type": "RCA_SUBMITTED", "work_item_id": "cc9a6503..."}
```
