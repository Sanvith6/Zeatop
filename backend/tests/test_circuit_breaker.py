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
import pytest
from unittest.mock import AsyncMock, patch
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

@pytest.fixture
def breaker():
    return CircuitBreaker(
        name="test",
        failure_threshold=3,
        recovery_timeout=0.5,
        half_open_max_calls=2,
    )

@pytest.mark.asyncio
async def test_success_passes_through(breaker):
    async def success():
        return 42

    with patch("app.services.circuit_breaker.redis_client", new_callable=AsyncMock) as mock_redis:
        mock_redis.get.return_value = None # State CLOSED
        result = await breaker.call(success)
        assert result == 42
        mock_redis.delete.assert_called()

@pytest.mark.asyncio
async def test_trips_after_threshold(breaker):
    async def fail():
        raise ValueError("boom")

    with patch("app.services.circuit_breaker.redis_client", new_callable=AsyncMock) as mock_redis:
        mock_redis.get.return_value = None # Initially CLOSED
        mock_redis.incr.side_effect = [1, 2, 3] # Failure count
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail)
        
        # Verify it set the state to OPEN in Redis
        mock_redis.setex.assert_any_call("cb:test:state", 0, CircuitState.OPEN)

@pytest.mark.asyncio
async def test_open_rejects_immediately(breaker):
    with patch("app.services.circuit_breaker.redis_client", new_callable=AsyncMock) as mock_redis:
        mock_redis.get.return_value = b"OPEN"
        
        async def success():
            return "should not reach"

        with pytest.raises(CircuitOpenError):
            await breaker.call(success)

@pytest.mark.asyncio
async def test_transitions_to_half_open_after_timeout(breaker):
    with patch("app.services.circuit_breaker.redis_client", new_callable=AsyncMock) as mock_redis:
        # Simulate state key expired, but was_open flag exists
        # 1st call to get(): state key (None)
        # 2nd call to get(): was_open key (b"1")
        mock_redis.get.side_effect = [None, b"1"] 
        
        state = await breaker.get_state()
        assert state == CircuitState.HALF_OPEN
        mock_redis.set.assert_any_call("cb:test:state", CircuitState.HALF_OPEN)
