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
