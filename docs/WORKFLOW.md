# Incident Workflow & State Machine

## 1. Lifecycle Overview

Every incident in Zeatop follows a strict, linear lifecycle enforced by a formal **State Pattern** implementation:

```
  ┌──────────┐    Investigate     ┌───────────────┐    Mark Resolved    ┌──────────┐    Close (RCA required)    ┌────────┐
  │   OPEN   │ ────────────────→  │ INVESTIGATING │ ──────────────────→ │ RESOLVED │ ──────────────────────→   │ CLOSED │
  └──────────┘                    └───────────────┘                     └──────────┘                           └────────┘
       │                                │                                    │                                     │
       │ (idempotent)                   │ (idempotent)                       │ (idempotent)                        │ (terminal)
       └────→ OPEN                      └────→ INVESTIGATING                └────→ RESOLVED                       ✕ No transitions
```

### Allowed Transitions

| From State | Allowed Target | Blocked Targets |
|-----------|---------------|-----------------|
| OPEN | INVESTIGATING, OPEN (idempotent) | RESOLVED, CLOSED |
| INVESTIGATING | RESOLVED, INVESTIGATING (idempotent) | OPEN, CLOSED |
| RESOLVED | CLOSED (with complete RCA), RESOLVED (idempotent) | OPEN, INVESTIGATING |
| CLOSED | CLOSED (idempotent) | ALL other states |

## 2. State Pattern Implementation

**File**: `backend/app/services/state_machine.py`

The system uses the **GoF State Pattern** — each state is a separate class with its own transition logic:

```
IncidentState (ABC)          ← Abstract base class
    ├── OpenState             ← Only allows → INVESTIGATING
    ├── InvestigatingState    ← Only allows → RESOLVED
    ├── ResolvedState         ← Only allows → CLOSED (with RCA check)
    └── ClosedState           ← Terminal state, no transitions
```

### Why State Pattern (not if/elif)

1. **Single Responsibility**: Each state's logic is encapsulated in its own class
2. **Open/Closed Principle**: Adding a new state (e.g., `ON_HOLD`) requires ONE new class — no modification of existing state logic
3. **Testability**: Each state can be unit-tested in isolation (see `backend/tests/test_state_machine.py`)

### Context Class

`WorkItemStateMachine` is the context class that:
1. Reads the current `status` from the database model
2. Initializes the correct state object
3. Delegates `transition()` calls to the active state
4. Updates the database model's `status` field on successful transitions

## 3. Transition Validation

### 3.1 Invalid Transition Blocking

When an invalid transition is attempted (e.g., OPEN → CLOSED), the state object raises `InvalidTransitionError`, which the router catches and returns as HTTP 409 Conflict:

**File**: `backend/app/services/workitems.py:102-105`
```python
try:
    WorkItemStateMachine(item).transition(new_state)
except InvalidTransitionError as exc:
    raise HTTPException(status_code=409, detail=str(exc))
```

### 3.2 RCA Enforcement

The `ResolvedState` has a special guard: it checks `has_complete_rca()` before allowing the CLOSED transition:

**File**: `backend/app/services/state_machine.py:56-64`
```python
class ResolvedState(IncidentState):
    def transition(self, new_state_name: str) -> None:
        if new_state_name == "CLOSED":
            if not self.context.has_complete_rca():
                raise InvalidTransitionError("Cannot close work item without a complete RCA")
```

A "complete" RCA requires ALL fields to be non-empty:
- `incident_start`
- `incident_end`
- `root_cause_category`
- `fix_applied`
- `prevention_steps`

### 3.3 Audit Trail

Every successful transition creates a `WorkItemStatusHistory` record:

**File**: `backend/app/services/workitems.py:106-108`
```python
if previous != item.status:
    item.updated_at = datetime.now(timezone.utc)
    session.add(WorkItemStatusHistory(
        work_item_id=item.id,
        from_status=previous,
        to_status=item.status
    ))
```

This provides a complete audit trail of who changed what and when, visible in the UI's "Timeline" tab.

## 4. Where Logic Lives

| Concern | File | Function/Class |
|---------|------|----------------|
| State definitions | `services/state_machine.py` | `OpenState`, `InvestigatingState`, etc. |
| Transition execution | `services/workitems.py` | `transition_workitem()` |
| API endpoint | `routers/workitems.py` | `PATCH /{id}/transition` |
| Audit trail | `models/db_models.py` | `WorkItemStatusHistory` |
| Unit tests | `tests/test_state_machine.py` | `TestValidTransitions`, `TestInvalidTransitions` |

## 5. Test Coverage

40 tests pass, including:
- 4 valid transition tests (forward flow)
- 5 invalid transition tests (skip/reverse blocking)
- 3 RCA enforcement tests (missing, incomplete, complete)
- Idempotent same-state transition test
