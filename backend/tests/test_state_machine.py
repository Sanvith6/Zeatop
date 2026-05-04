"""
Unit tests for the incident state machine.

Tests cover:
  - Valid forward transitions (OPEN → INVESTIGATING → RESOLVED → CLOSED)
  - Invalid skip transitions (OPEN → RESOLVED, OPEN → CLOSED)
  - RCA enforcement on CLOSED transition
  - Idempotent same-state transitions
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# We need to set up the environment before importing app modules
import os
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGO_DSN", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.state_machine import InvalidTransitionError, WorkItemStateMachine


def make_work_item(status: str = "OPEN", rca=None):
    """Create a mock WorkItem for testing."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.status = status
    item.rca = rca
    return item


def make_complete_rca():
    """Create a mock RCA with all required fields."""
    rca = MagicMock()
    rca.incident_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rca.incident_end = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    rca.root_cause_category = "Infrastructure"
    rca.fix_applied = "Restarted the primary database node"
    rca.prevention_steps = "Add automated failover and health monitoring"
    return rca


def make_incomplete_rca():
    """Create a mock RCA missing required fields."""
    rca = MagicMock()
    rca.incident_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rca.incident_end = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    rca.root_cause_category = "Infrastructure"
    rca.fix_applied = ""  # Empty — incomplete
    rca.prevention_steps = ""  # Empty — incomplete
    return rca


# --- Valid transitions ---

class TestValidTransitions:
    def test_open_to_investigating(self):
        item = make_work_item("OPEN")
        sm = WorkItemStateMachine(item)
        sm.transition("INVESTIGATING")
        assert item.status == "INVESTIGATING"

    def test_investigating_to_resolved(self):
        item = make_work_item("INVESTIGATING")
        sm = WorkItemStateMachine(item)
        sm.transition("RESOLVED")
        assert item.status == "RESOLVED"

    def test_resolved_to_closed_with_complete_rca(self):
        rca = make_complete_rca()
        item = make_work_item("RESOLVED", rca=rca)
        sm = WorkItemStateMachine(item)
        sm.transition("CLOSED")
        assert item.status == "CLOSED"

    def test_same_state_is_idempotent(self):
        item = make_work_item("OPEN")
        sm = WorkItemStateMachine(item)
        sm.transition("OPEN")  # No-op
        assert item.status == "OPEN"


# --- Invalid transitions ---

class TestInvalidTransitions:
    def test_open_to_resolved_blocked(self):
        item = make_work_item("OPEN")
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            sm.transition("RESOLVED")

    def test_open_to_closed_blocked(self):
        item = make_work_item("OPEN")
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            sm.transition("CLOSED")

    def test_investigating_to_closed_blocked(self):
        item = make_work_item("INVESTIGATING")
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            sm.transition("CLOSED")

    def test_closed_to_anything_blocked(self):
        rca = make_complete_rca()
        item = make_work_item("CLOSED", rca=rca)
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            sm.transition("OPEN")

    def test_resolved_to_open_blocked(self):
        item = make_work_item("RESOLVED")
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            sm.transition("OPEN")


# --- RCA enforcement ---

class TestRCAEnforcement:
    def test_close_without_rca_blocked(self):
        item = make_work_item("RESOLVED", rca=None)
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="RCA"):
            sm.transition("CLOSED")

    def test_close_with_incomplete_rca_blocked(self):
        rca = make_incomplete_rca()
        item = make_work_item("RESOLVED", rca=rca)
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="RCA"):
            sm.transition("CLOSED")

    def test_close_with_complete_rca_allowed(self):
        rca = make_complete_rca()
        item = make_work_item("RESOLVED", rca=rca)
        sm = WorkItemStateMachine(item)
        sm.transition("CLOSED")
        assert item.status == "CLOSED"
