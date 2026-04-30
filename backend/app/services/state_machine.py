from app.models.db_models import WorkItem


class InvalidTransitionError(ValueError):
    pass


class WorkItemStateMachine:
    allowed_transitions: dict[str, set[str]] = {
        "OPEN": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED"},
        "RESOLVED": {"CLOSED"},
        "CLOSED": set(),
    }

    def __init__(self, work_item: WorkItem) -> None:
        self.work_item = work_item

    def transition(self, new_state: str) -> None:
        current = self.work_item.status
        if new_state == current:
            return
        if new_state not in self.allowed_transitions.get(current, set()):
            raise InvalidTransitionError(f"Cannot transition from {current} to {new_state}")
        if new_state == "CLOSED" and not self._has_complete_rca():
            raise InvalidTransitionError("Cannot close work item without a complete RCA")
        self.work_item.status = new_state

    def _has_complete_rca(self) -> bool:
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
