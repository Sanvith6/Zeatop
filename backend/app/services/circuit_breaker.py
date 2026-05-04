"""
Distributed circuit breaker — prevents cascading failures across workers.

Backpressure and failure isolation for downstream dependencies (Postgres/Mongo).
Trips to OPEN state after N failures, allowing the dependency to recover 
without being hammered by the worker pool. Probing via HALF_OPEN ensures 
safe recovery before resuming full throughput.
"""

import asyncio
import logging
from enum import StrEnum

from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is OPEN and calls are being rejected."""
    pass


class CircuitBreaker:
    """Distributed circuit breaker backed by Redis."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        # Redis Keys
        self._state_key = f"cb:{name}:state"
        self._fail_key = f"cb:{name}:failures"
        self._half_open_key = f"cb:{name}:half_open_calls"

    async def get_state(self) -> CircuitState:
        """Fetch current state from Redis with lazy OPEN -> HALF_OPEN transition."""
        state = await redis_client.get(self._state_key)
        if state:
            return CircuitState(state.decode() if isinstance(state, bytes) else state)
        
        # If the state key is missing, check if we were previously OPEN.
        # If so, we transition to HALF_OPEN for probing.
        was_open = await redis_client.get(f"cb:{self.name}:was_open")
        if was_open:
            logger.info("Circuit breaker [%s] cooldown finished — transitioning to HALF_OPEN", self.name)
            await redis_client.set(self._state_key, CircuitState.HALF_OPEN)
            await redis_client.delete(f"cb:{self.name}:was_open")
            await redis_client.set(self._half_open_key, 0)
            return CircuitState.HALF_OPEN
            
        return CircuitState.CLOSED

    async def call(self, func, *args, **kwargs):
        """Execute `func` through the distributed circuit breaker."""
        state = await self.get_state()

        if state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker [{self.name}] is OPEN (distributed) — failing fast"
            )

        if state == CircuitState.HALF_OPEN:
            # Atomic increment to limit probe calls across all workers
            calls = await redis_client.incr(self._half_open_key)
            if int(calls) > self.half_open_max_calls:
                raise CircuitOpenError(
                    f"Circuit breaker [{self.name}] is HALF_OPEN — max probe calls reached"
                )

        try:
            result = await func(*args, **kwargs)
            await self._on_success(state)
            return result
        except Exception as exc:
            await self._on_failure(exc)
            raise

    async def _on_success(self, state: CircuitState) -> None:
        """Reset failures on success. Close circuit if we were probing."""
        if state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker [%s] recovered — transitioning HALF_OPEN → CLOSED", self.name)
            await redis_client.delete(self._state_key)
            await redis_client.delete(self._fail_key)
            await redis_client.delete(self._half_open_key)
        else:
            # Normal success in CLOSED state clears any intermittent failures
            await redis_client.delete(self._fail_key)

    async def _on_failure(self, exc: Exception) -> None:
        """Increment failures in Redis. Trip circuit if threshold reached."""
        fails = await redis_client.incr(self._fail_key)
        # Keep failure count around for recovery timeout window
        await redis_client.expire(self._fail_key, int(self.recovery_timeout * 2))
        
        logger.warning(
            "Circuit breaker [%s] recorded failure %s/%d: %s",
            self.name, fails, self.failure_threshold, exc,
        )

        if int(fails) >= self.failure_threshold:
            logger.error(
                "Circuit breaker [%s] TRIPPED — transitioning to OPEN for %.0fs",
                self.name, self.recovery_timeout,
            )
            # Trip to OPEN with TTL
            await redis_client.setex(self._state_key, int(self.recovery_timeout), CircuitState.OPEN)
            # Set 'was_open' flag to trigger HALF_OPEN transition after TTL expires
            await redis_client.setex(f"cb:{self.name}:was_open", int(self.recovery_timeout + 60), "1")


# ---------------------------------------------------------------------------
# Module-level circuit breaker instances.
# ---------------------------------------------------------------------------
mongo_breaker = CircuitBreaker(name="mongodb", failure_threshold=5, recovery_timeout=30.0)
postgres_breaker = CircuitBreaker(name="postgresql", failure_threshold=5, recovery_timeout=30.0)
