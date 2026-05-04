# Sample Data & Simulation Scripts

## Overview

The `scripts/` directory contains production-quality simulation tools that demonstrate the system's ability to handle realistic failure scenarios. Each script authenticates via JWT, sends signals at controlled rates, and validates the full ingestion pipeline.

---

## 1. simulate_failure.py — RDBMS & MCP Outage

**Scenario**: Primary database goes down, followed by a control plane failure.

```bash
python scripts/simulate_failure.py
```

### What It Does

| Phase | Component | Type | Severity | Signals | Duration |
|-------|-----------|------|----------|---------|----------|
| 1 | `DB_PRIMARY_01` | rdbms | P0 | 150 | 8s |
| 2 | `MCP_HOST_02` | mcp | P0 | 80 | 5s |
| 3 | Random noise (4 cache/queue components) | cache/queue | P2/P3 | 30 | 3s |

### Expected Result

- 2 P0 incidents created (DB_PRIMARY_01, MCP_HOST_02)
- Noise signals are debounced — cache/queue components stay below the 100-signal threshold, so they do NOT create incidents
- Dashboard shows 99%+ noise reduction

### Example Signal Payload

```json
{
  "component_id": "DB_PRIMARY_01",
  "component_type": "rdbms",
  "error_message": "Primary database connection timeout",
  "severity": "P0",
  "timestamp": "2026-05-04T10:30:00Z"
}
```

---

## 2. simulate_failure2.py — External Dependencies

**Scenario**: Payment gateway returns 503, API gateway has configuration error causing 504 timeouts.

```bash
python scripts/simulate_failure2.py
```

| Phase | Component | Type | Severity | Signals | Duration |
|-------|-----------|------|----------|---------|----------|
| 1 | `PAYMENT_GATEWAY_01` | external | P1 | 120 | 6s |
| 2 | `API_GATEWAY_PROD` | compute | P0 | 60 | 4s |

### Expected Result

- 2 incidents created with distinct component types
- AI RCA correctly identifies "External Dependency" for the payment gateway
- Severity auto-classification may upgrade the API gateway signals based on component baseline

---

## 3. simulate_failure3.py — Resource Exhaustion

**Scenario**: Cache cluster runs out of memory, storage node has disk I/O saturation.

```bash
python scripts/simulate_failure3.py
```

| Phase | Component | Type | Severity | Signals | Duration |
|-------|-----------|------|----------|---------|----------|
| 1 | `CACHE_CLUSTER_01` | cache | P2 | 200 | 10s |
| 2 | `STORAGE_NODE_05` | storage | P1 | 90 | 5s |

### Expected Result

- 2 incidents created
- Cache cluster signals demonstrate high-volume debouncing (200 signals → 1 incident)
- AI RCA suggests memory allocation fixes and eviction policy adjustments

---

## 4. Running All Simulations

```bash
# Run all three in sequence
python scripts/simulate_failure.py
python scripts/simulate_failure2.py
python scripts/simulate_failure3.py
```

After running all three, the dashboard should show **6+ distinct incidents** across different component types, severities, and failure categories.

---

## 5. Manual Signal Injection (PowerShell)

For ad-hoc testing without scripts:

```powershell
# Step 1: Get JWT token
$body = @{username="sre-intern"; password="zeotap-local"} | ConvertTo-Json
$token = (Invoke-RestMethod -Uri "http://localhost:8000/api/auth/token" -Method Post -Body $body -ContentType "application/json").access_token

# Step 2: Send a single signal
$signal = @{
    component_id = "SERVER_01"
    component_type = "compute"
    severity = "P0"
    error_message = "CPU usage at 99%"
    timestamp = [System.DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/signals" -Method Post -Body $signal -ContentType "application/json" -Headers @{Authorization="Bearer $token"}
```

---

## 6. Additional Scripts

| Script | Purpose |
|--------|---------|
| `chaos_demo.py` | Stops PostgreSQL mid-ingestion to demonstrate circuit breaker activation |
| `chaos_test.py` | Automated chaos engineering validation |
| `high_load.py` | High-throughput stress test |
| `load_test.py` | Standard load test with metrics collection |
| `load_test_k6.js` | k6-based load test for benchmarking (requires k6 installed) |
| `qa_validation.py` | Automated QA validation of all system features |
| `load_incident.py` | Single-incident load generator |
