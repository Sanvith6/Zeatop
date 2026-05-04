# Sample Data & Simulation Scripts

## Overview

The `scripts/` directory contains production-quality simulation tools that demonstrate the system's ability to handle realistic failure scenarios. Each script authenticates via JWT, sends signals at controlled rates, and validates the full ingestion pipeline.

---

## 1. simulate_failure.py — Consolidated SRE Failure Simulations

The primary tool for demonstrating system resilience. This script includes multiple scenarios that model real-world infrastructure failures.

```bash
# Run all failure scenarios sequentially
python scripts/simulate_failure.py

# Run specific scenarios only
python scripts/simulate_failure.py 1  # Infrastructure (RDBMS & MCP)
python scripts/simulate_failure.py 2  # External Dependencies (Stripe)
python scripts/simulate_failure.py 3  # Resource Exhaustion (Cache OOM)
```

### Simulation Scenarios

| Scenario | Component Type | Severity | Failure Type | Expected Result |
|----------|----------------|----------|--------------|-----------------|
| **1** | RDBMS, MCP | P0 | Outage | 2 Critical incidents, noise debounced |
| **2** | External, Compute | P1, P0 | Timeout | AI RCA identifies 3rd party root cause |
| **3** | Cache, Storage | P2, P1 | OOM/Latency | 200+ signals consolidated into 1 incident |

### Example Signal Payload (JSON)

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

## 2. Chaos & Load Testing

For more intensive validation:

```bash
python scripts/high_load.py   # High-throughput stress test (10k+ signals)
python scripts/chaos_test.py  # Automated chaos engineering validation
```

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
