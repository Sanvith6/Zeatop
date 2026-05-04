# Root Cause Analysis (RCA) Flow

## 1. Why RCA is Mandatory

The system enforces a strict rule: **No incident can be closed without a complete Root Cause Analysis.**

This is an SRE best practice that ensures:
1. Every production incident is formally investigated
2. Prevention steps are documented to reduce repeat failures
3. MTTR (Mean Time To Resolution) is accurately tracked for SLA reporting

### Enforcement Point

The enforcement happens at the **State Machine level**, not the API level. This means it's impossible to bypass — even direct database manipulation would be caught on the next state transition attempt.

**File**: `backend/app/services/state_machine.py:56-64`

```python
class ResolvedState(IncidentState):
    def transition(self, new_state_name: str) -> None:
        if new_state_name == "CLOSED":
            if not self.context.has_complete_rca():
                raise InvalidTransitionError(
                    "Cannot close work item without a complete RCA"
                )
```

## 2. RCA Schema

### Database Model

**File**: `backend/app/models/db_models.py:38-48`

```
RCA Table
├── id (UUID, PK)
├── work_item_id (UUID, FK → work_items.id)
├── incident_start (DateTime)
├── incident_end (DateTime)
├── root_cause_category (String) — one of 5 categories
├── fix_applied (Text)
├── prevention_steps (Text)
└── submitted_at (DateTime, auto-set)
```

### Root Cause Categories

**File**: `backend/app/models/schemas.py:32-37`

| Category | When to Use |
|----------|-------------|
| Infrastructure | Hardware failures, network issues, resource exhaustion |
| Code Deployment | Bugs introduced by recent deployments |
| Configuration Change | Misconfigured parameters, threshold changes |
| External Dependency | Third-party service outages (Stripe, AWS, etc.) |
| Unknown | Root cause could not be determined |

### Validation Rules

**File**: `backend/app/models/schemas.py:65-76`

1. All fields are required (`min_length=1` on text fields)
2. **Whitespace Stripping**: Text fields (`fix_applied`, `prevention_steps`) are automatically stripped. Whitespace-only input is rejected.
3. `incident_end` must be strictly after `incident_start`
4. `root_cause_category` must be one of the 5 valid enum values

```python
class RCARequest(BaseModel):
    incident_start: datetime
    incident_end: datetime
    root_cause_category: RootCauseCategory
    fix_applied: str = Field(min_length=1)
    prevention_steps: str = Field(min_length=1)

    @field_validator("fix_applied", "prevention_steps", mode="before")
    @classmethod
    def strip_whitespace(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "RCARequest":
        if self.incident_end <= self.incident_start:
            raise ValueError("incident_end must be after incident_start")
        return self
```

## 3. MTTR Calculation

**File**: `backend/app/services/workitems.py:137-138`

```python
mttr_minutes = (incident_end - incident_start).total_seconds() / 60
```

MTTR is calculated as `incident_end - incident_start` (the duration of the actual incident window as reported by the responder), stored in minutes on the `WorkItem` model, and displayed on the dashboard.

## 4. AI-Powered RCA Suggestions

**File**: `backend/app/services/ai_rca.py`

The system integrates with **Groq (Llama 3.3 70B)** to auto-generate RCA suggestions:

### How It Works

1. When the user clicks "Suggest" on the RCA form, the frontend calls `POST /api/workitems/{id}/suggest-rca`
2. The backend fetches the last 500 signals for that incident from MongoDB
3. Unique error patterns are extracted (deduplication to reduce token noise)
4. A structured prompt is sent to Groq with:
   - Component ID, Type, Severity
   - Observed error patterns
5. The model returns a JSON object with `root_cause_category`, `fix_applied`, `prevention_steps`
6. The frontend auto-fills the RCA form with the suggestion

### System Prompt

The AI is instructed to act as a **Staff Site Reliability Engineer** with specific instructions to:
- Identify Direct Cause vs. Root Cause
- Categorize into one of the 5 valid categories
- Suggest SRE-grade fixes (circuit breaking, progressive rollout, horizontal scaling)
- Provide prevention steps aimed at improving MTBF

### Fallback Behavior

| Scenario | Behavior |
|----------|----------|
| API key missing/placeholder | Returns `Unknown` category with setup instructions |
| Groq API error (rate limit, timeout) | Returns `Unknown` category with error details |
| Invalid JSON response | Caught by exception handler, returns fallback |

### Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| Model | `llama-3.3-70b-versatile` | Best balance of quality and speed |
| Temperature | `0.15` | Low for deterministic, reproducible analysis |
| Max Tokens | `500` | Sufficient for concise SRE analysis |
| Response Format | `json_object` | Ensures parseable structured output |

## 5. Full RCA Submission Flow

```
User clicks "Submit RCA" on frontend
    ↓
POST /api/workitems/{id}/rca
    ↓
[1] Validate payload (Pydantic: dates, category, non-empty fields)
    ↓
[2] Check work item exists and is not CLOSED
    ↓
[3] Calculate MTTR = incident_end - incident_start
    ↓
[4] Create RCA record in PostgreSQL
    ↓
[5] Link RCA to Work Item (set rca_id, mttr_minutes)
    ↓
[6] Invalidate dashboard cache
    ↓
[7] Broadcast via Redis Pub/Sub → WebSocket → Frontend
    ↓
User sees updated incident with RCA and MTTR
    ↓
"Close Incident" button now available (state machine allows RESOLVED → CLOSED)
```

## 6. Where Logic Lives

| Concern | File | Function |
|---------|------|----------|
| RCA submission | `services/workitems.py` | `submit_rca()` |
| AI suggestion | `services/ai_rca.py` | `get_ai_rca_suggestion()` |
| Schema validation | `models/schemas.py` | `RCARequest` |
| Database model | `models/db_models.py` | `RCA` class |
| State enforcement | `services/state_machine.py` | `ResolvedState.transition()` |
| API endpoints | `routers/workitems.py` | `POST /{id}/rca`, `POST /{id}/suggest-rca` |
