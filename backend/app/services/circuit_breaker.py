"""
Circuit Breaker — Production-grade resilience pattern.

WHY THIS EXISTS:
In a distributed system, downstream dependencies (PostgreSQL, MongoDB) can fail
intermittently or go down entirely. Without a circuit breaker, the worker pool
would continue hammering the failed service, causing:

  1. Thread/connection pool exhaustion in the worker
  2. Cascading latency spikes (every request waits for TCP timeout)
  3. Flooding the recovering database with a thundering herd of retries

The circuit breaker "trips" after a configurable number of consecutive failures,
immediately rejecting calls for a cooldown period. This gives the downstream
service time to recover and prevents resource exhaustion in the worker.

STATE MACHINE:
  CLOSED  → normal operation, calls pass through
  OPEN    → circuit tripped, all calls fail-fast without touching the dependency
  HALF_OPEN → after cooldown, allow a small number of probe calls to test recovery

This is the same pattern used by Netflix Hystrix, AWS App Mesh, and Envoy proxy,
implemented here at the application level for simplicity.
"""

import asyncio
import logging
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is OPEN and calls are being rejected."""
    pass


class CircuitBreaker:
    """
    Async-safe circuit breaker with configurable thresholds.

    Thread safety note:
    This implementation is designed for single-process async (asyncio) usage.
    The state transitions are safe because asyncio is cooperative — only one
    coroutine runs at a time within a single event loop. For multi-process
    deployments, a distributed circuit breaker backed by Redis would be needed.
    """

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

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """
        Check if the circuit should transition from OPEN → HALF_OPEN.
        This is evaluated lazily on each access rather than using a timer,
        which avoids background tasks and is simpler to reason about.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info(
                    "Circuit breaker [%s] transitioning OPEN → HALF_OPEN after %.1fs cooldown",
                    self.name, elapsed,
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    async def call(self, func, *args, **kwargs):
        """
        Execute `func` through the circuit breaker.
        If the circuit is OPEN, raises CircuitOpenError immediately.
        """
        current_state = self.state  # triggers lazy OPEN → HALF_OPEN check

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker [{self.name}] is OPEN — failing fast to protect downstream"
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                raise CircuitOpenError(
                    f"Circuit breaker [{self.name}] is HALF_OPEN — max probe calls reached"
                )
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            raise

    def _on_success(self) -> None:
        """Reset failure count on success. Close circuit if we're in HALF_OPEN."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            # Require at least half_open_max_calls successes to close
            if self._success_count >= self.half_open_max_calls:
                logger.info("Circuit breaker [%s] recovered — transitioning HALF_OPEN → CLOSED", self.name)
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            self._failure_count = 0

    def _on_failure(self, exc: Exception) -> None:
        """Increment failure count. Trip circuit if threshold exceeded."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        logger.warning(
            "Circuit breaker [%s] recorded failure %d/%d: %s",
            self.name, self._failure_count, self.failure_threshold, exc,
        )
        if self._failure_count >= self.failure_threshold:
            logger.error(
                "Circuit breaker [%s] TRIPPED — transitioning to OPEN state for %.0fs",
                self.name, self.recovery_timeout,
            )
            self._state = CircuitState.OPEN
            self._success_count = 0


# ---------------------------------------------------------------------------
# Module-level circuit breaker instances.
#
# WHY separate breakers per dependency:
# If only MongoDB is down but PostgreSQL is healthy, we should still process
# signals that only need Postgres writes. Separate breakers allow independent
# failure isolation — the same principle behind bulkhead patterns.
# ---------------------------------------------------------------------------

mongo_breaker = CircuitBreaker(name="mongodb", failure_threshold=5, recovery_timeout=30.0)
postgres_breaker = CircuitBreaker(name="postgresql", failure_threshold=5, recovery_timeout=30.0)
