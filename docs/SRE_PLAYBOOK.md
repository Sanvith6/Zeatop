# Zetatop SRE Playbook 🛡️

This playbook outlines the standard operating procedures (SOPs) for responding to incidents within the Zetatop Incident Management System.

## 1. Incident Lifecycle States

- **OPEN**: Incident detected by debouncing engine. Signals are being aggregated.
- **INVESTIGATING**: Engineer has acknowledged the incident and is analyzing raw signals.
- **RESOLVED**: Root cause identified and fix applied. RCA submitted.
- **CLOSED**: Final verification complete. Incident is archived.

## 2. Common Failure Scenarios

### Scenario A: RDBMS Outage (P0)
- **Signal**: `Connection timeout`, `Connection refused` from `rdbms` components.
- **System Impact**: Circuit breaker trips for PostgreSQL. Signals are routed to MongoDB DLQ.
- **Response**: 
  1. Check PostgreSQL container health: `docker ps`.
  2. Verify network connectivity between worker and DB.
  3. Check PostgreSQL logs for disk space or memory issues.
  4. Once restored, monitor Circuit Breaker transition to `HALF_OPEN`.

### Scenario B: Cache Cluster Degradation (P2)
- **Signal**: `Key not found`, `Latency spike` from `cache` components.
- **System Impact**: AlertStrategy sends warning. Dashboard shows yellow severity.
- **Response**:
  1. Flush stale keys if necessary.
  2. Scale Redis cluster if memory usage > 80%.
  3. Verify eviction policy settings.

### Scenario C: High Signal Burst (Backpressure)
- **Signal**: `Queue depth > 70%`, `HTTP 429` errors in ingestion logs.
- **System Impact**: Adaptive throttling active.
- **Response**:
  1. Scale background workers: `docker-compose up --scale worker=10`.
  2. Check for "noisy neighbor" components triggering excessive signals.
  3. Adjust debounce window if noise is sustained but non-critical.

## 3. Post-Mortem Requirements

Every P0/P1 incident **must** have a completed RCA before it can be moved to the `CLOSED` state. The RCA must include:
1. **Accurate Timestamps**: Incident start and end for MTTR calculation.
2. **Root Cause Category**: Classification for historical trend analysis.
3. **Fix Applied**: Detailed description of the technical mitigation.
4. **Prevention Steps**: Concrete actions to prevent recurrence (e.g., adding automated restart policies).

## 4. AI-Assisted RCA

Leverage the **AI Suggest** tool in the RCA form for rapid analysis of complex signal patterns. The AI uses Groq (Llama 3) to correlate multiple error messages across components.

---
*Created by Zetatop SRE Team*
