"""
Incident state machine — enforces strict SRE lifecycle transitions.

Ensures data integrity and compliance by validating state transitions 
(OPEN -> INVESTIGATING -> RESOLVED -> CLOSED) and mandating a complete 
Root Cause Analysis (RCA) before closure.
"""

from app.models.db_models import WorkItem


class InvalidTransitionError(ValueError):
    """Raised when an invalid state transition is attempted."""
    pass


class WorkItemStateMachine:
    """
    Enforces the incident lifecycle:
      OPEN → INVESTIGATING → RESOLVED → CLOSED

    DESIGN DECISION: Forward-only transitions.
    We don't allow backwards transitions (e.g., RESOLVED → OPEN) because:
      - It would complicate MTTR calculation
      - It creates confusing timelines
      - If a resolved incident recurs, it should be a NEW incident
    """

    allowed_transitions: dict[str, set[str]] = {
        "OPEN": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED"},
        "RESOLVED": {"CLOSED"},
        "CLOSED": set(),  # Terminal state — no transitions allowed
    }

    def __init__(self, work_item: WorkItem) -> None:
        self.work_item = work_item

    def transition(self, new_state: str) -> None:
        """
        Attempt to transition the work item to a new state.

        Validates:
          1. The transition is allowed by the state machine
          2. CLOSED requires a complete RCA (all fields filled)

        Raises InvalidTransitionError if validation fails.
        """
        current = self.work_item.status
        if new_state == current:
            return  # Idempotent — no-op for same state

        if new_state not in self.allowed_transitions.get(current, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {current} to {new_state}"
            )

        if new_state == "CLOSED" and not self._has_complete_rca():
            raise InvalidTransitionError(
                "Cannot close work item without a complete RCA"
            )

        self.work_item.status = new_state

    def _has_complete_rca(self) -> bool:
        """
        Check if the work item has a complete Root Cause Analysis.

        ALL fields are required — partial RCAs don't count. This ensures
        operators can't shortcut the post-incident review process.
        """
        rca = self.work_item.rca
        if rca is None:
            return False
        return all(
            [
                rca.incident_start,
                rca.incident_end,
                rca.root_cause_category,
                rca.fix_applied,
                rca.prevention_steps,
            ]
        )
