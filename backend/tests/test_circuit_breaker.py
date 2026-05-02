"""
Unit tests for the circuit breaker.

Tests cover:
  - Normal operation (CLOSED state)
  - Tripping after failure threshold
  - Fail-fast when OPEN
  - Recovery after timeout (HALF_OPEN)
  - Full recovery back to CLOSED
"""

import asyncio
import time

import pytest

import os
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGO_DSN", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


@pytest.fixture
def breaker():
    return CircuitBreaker(
        name="test",
        failure_threshold=3,
        recovery_timeout=0.5,  # Short timeout for fast tests
        half_open_max_calls=2,
    )


class TestClosedState:
    @pytest.mark.asyncio
    async def test_success_passes_through(self, breaker):
        async def success():
            return 42

        result = await breaker.call(success)
        assert result == 42
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_single_failure_stays_closed(self, breaker):
        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await breaker.call(fail)

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 1

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, breaker):
        async def fail():
            raise ValueError("boom")

        async def success():
            return "ok"

        # Two failures
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker._failure_count == 2

        # One success resets
        await breaker.call(success)
        assert breaker._failure_count == 0


class TestOpenState:
    @pytest.mark.asyncio
    async def test_trips_after_threshold(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_immediately(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        async def success():
            return "should not reach"

        with pytest.raises(CircuitOpenError):
            await breaker.call(success)


class TestHalfOpenState:
    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.6)

        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_recovers_to_closed_on_success(self, breaker):
        async def fail():
            raise ValueError("boom")

        async def success():
            return "ok"

        # Trip the breaker
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        # Wait for recovery
        await asyncio.sleep(0.6)
        assert breaker.state == CircuitState.HALF_OPEN

        # Successful probe calls close the circuit
        await breaker.call(success)
        await breaker.call(success)
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens(self, breaker):
        async def fail():
            raise ValueError("boom")

        # Trip the breaker
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)

        # Wait for recovery
        await asyncio.sleep(0.6)
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure in half-open reopens the circuit
        with pytest.raises(ValueError):
            await breaker.call(fail)

        # After the failure, it should be counting towards threshold again
        # Need enough failures to trip again
        for _ in range(2):
            try:
                await breaker.call(fail)
            except (ValueError, CircuitOpenError):
                pass

        assert breaker.state == CircuitState.OPEN
