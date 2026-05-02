"""
Unit tests for the severity auto-classifier.

Tests cover:
  - Correct baseline classification per component type
  - Severity upgrade when underclassified
  - No downgrade when overclassified
  - Unknown component types trusted as-is
"""

import os
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGO_DSN", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.classifier import classify_severity


class TestBaselineClassification:
    def test_rdbms_baseline_is_p0(self):
        assert classify_severity("rdbms", "P0") == "P0"

    def test_mcp_baseline_is_p0(self):
        assert classify_severity("mcp", "P0") == "P0"

    def test_api_baseline_is_p1(self):
        assert classify_severity("api", "P1") == "P1"

    def test_queue_baseline_is_p1(self):
        assert classify_severity("queue", "P1") == "P1"

    def test_cache_baseline_is_p2(self):
        assert classify_severity("cache", "P2") == "P2"

    def test_nosql_baseline_is_p2(self):
        assert classify_severity("nosql", "P2") == "P2"


class TestSeverityUpgrade:
    def test_rdbms_p2_upgraded_to_p0(self):
        assert classify_severity("rdbms", "P2") == "P0"

    def test_rdbms_p3_upgraded_to_p0(self):
        assert classify_severity("rdbms", "P3") == "P0"

    def test_api_p3_upgraded_to_p1(self):
        assert classify_severity("api", "P3") == "P1"

    def test_cache_p3_upgraded_to_p2(self):
        assert classify_severity("cache", "P3") == "P2"

    def test_mcp_p1_upgraded_to_p0(self):
        assert classify_severity("mcp", "P1") == "P0"


class TestNoDowngrade:
    def test_cache_p0_stays_p0(self):
        """Producer says P0, classifier baseline is P2 — trust the producer."""
        assert classify_severity("cache", "P0") == "P0"

    def test_api_p0_stays_p0(self):
        assert classify_severity("api", "P0") == "P0"

    def test_queue_p0_stays_p0(self):
        assert classify_severity("queue", "P0") == "P0"


class TestUnknownComponents:
    def test_unknown_type_trusted(self):
        assert classify_severity("cdn", "P3") == "P3"

    def test_unknown_type_p0_trusted(self):
        assert classify_severity("unknown_service", "P0") == "P0"
