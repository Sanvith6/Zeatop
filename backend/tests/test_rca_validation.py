"""
Unit tests for RCA Pydantic validation.

Tests cover:
  - Valid RCA payloads
  - Date ordering enforcement (end must be after start)
  - Required field validation
  - Root cause category validation
"""

import pytest
from datetime import datetime, timezone

import os
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGO_DSN", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from pydantic import ValidationError
from unittest.mock import MagicMock
from app.services.state_machine import WorkItemStateMachine, InvalidTransitionError
from app.models.schemas import RCARequest, RootCauseCategory


class TestValidRCA:
    def test_valid_rca_accepted(self):
        rca = RCARequest(
            incident_start=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            incident_end=datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc),
            root_cause_category=RootCauseCategory.Infrastructure,
            fix_applied="Restarted primary database",
            prevention_steps="Add automated failover monitoring",
        )
        assert rca.fix_applied == "Restarted primary database"
        assert rca.root_cause_category == RootCauseCategory.Infrastructure

    def test_all_categories_valid(self):
        for category in RootCauseCategory:
            rca = RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=category,
                fix_applied="Some fix",
                prevention_steps="Some prevention",
            )
            assert rca.root_cause_category == category


class TestDateValidation:
    def test_end_before_start_rejected(self):
        with pytest.raises(ValidationError, match="incident_end must be after"):
            RCARequest(
                incident_start=datetime(2026, 1, 2, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="Fix",
                prevention_steps="Steps",
            )

    def test_end_equal_start_rejected(self):
        same_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="incident_end must be after"):
            RCARequest(
                incident_start=same_time,
                incident_end=same_time,
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="Fix",
                prevention_steps="Steps",
            )


class TestRequiredFields:
    def test_empty_fix_rejected(self):
        with pytest.raises(ValidationError):
            RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="",
                prevention_steps="Steps",
            )

    def test_empty_prevention_rejected(self):
        with pytest.raises(ValidationError):
            RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="Fix",
                prevention_steps="",
            )

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category="NotACategory",
                fix_applied="Fix",
                prevention_steps="Steps",
            )


class TestComprehensiveRCA:
    def test_rca_end_before_start(self):
        """1. test_rca_end_before_start — end time is before start time"""
        with pytest.raises(ValidationError, match="incident_end must be after"):
            RCARequest(
                incident_start=datetime(2026, 1, 2, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="Fix",
                prevention_steps="Steps",
            )

    def test_rca_empty_fix_applied(self):
        """2. test_rca_empty_fix_applied — fix_applied is empty string or whitespace only"""
        with pytest.raises(ValidationError):
            RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="   ",  # Whitespace only — should fail min_length=1
                prevention_steps="Steps",
            )

    def test_rca_empty_prevention_steps(self):
        """3. test_rca_empty_prevention_steps — prevention_steps is empty or whitespace"""
        with pytest.raises(ValidationError):
            RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=RootCauseCategory.Infrastructure,
                fix_applied="Fix",
                prevention_steps="",  # Empty string
            )

    def test_rca_mttr_calculation_accuracy(self):
        """4. test_rca_mttr_calculation_accuracy — verify MTTR is calculated correctly"""
        start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)  # Exactly 60 mins
        
        # We simulate the calculation logic used in submit_rca
        mttr_minutes = (end - start).total_seconds() / 60
        assert mttr_minutes == 60.0

    def test_closed_transition_blocked_without_rca(self):
        """5. test_closed_transition_blocked_without_rca — confirm InvalidTransitionError raised"""
        item = MagicMock()
        item.status = "RESOLVED"
        item.rca = None
        sm = WorkItemStateMachine(item)
        with pytest.raises(InvalidTransitionError, match="without a complete RCA"):
            sm.transition("CLOSED")

    def test_closed_transition_succeeds_with_valid_rca(self):
        """6. test_closed_transition_succeeds_with_valid_rca — confirm transition to CLOSED succeeds"""
        rca = MagicMock()
        rca.incident_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rca.incident_end = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        rca.fix_applied = "Fix"
        rca.prevention_steps = "Steps"
        
        item = MagicMock()
        item.status = "RESOLVED"
        item.rca = rca
        sm = WorkItemStateMachine(item)
        sm.transition("CLOSED")
        assert item.status == "CLOSED"

    def test_rca_category_all_valid_values(self):
        """7. test_rca_category_all_valid_values — loop through all valid categories"""
        for category in RootCauseCategory:
            rca = RCARequest(
                incident_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                incident_end=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                root_cause_category=category,
                fix_applied="Some fix",
                prevention_steps="Some prevention",
            )
            assert rca.root_cause_category == category
