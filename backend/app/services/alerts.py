"""
Alert strategy — dispatches notifications based on component type.

WHY STRATEGY PATTERN (not if/elif chains):
Different component types require different escalation behaviors:
  - RDBMS failure → page on-call immediately (P0 blast radius)
  - Cache degradation → warn in Slack (performance impact, not outage)
  - API errors → escalate to service owner (P1 service-affecting)

The Strategy pattern encapsulates each escalation policy in its own class.
Adding a new component type (e.g., "cdn") requires adding ONE class and ONE
dictionary entry — no touching existing alert logic.

WHY WEBHOOK (not direct integration):
The worker sends alerts via HTTP POST to a webhook endpoint. This decouples
the alert dispatch from the specific notification service (PagerDuty, Slack,
OpsGenie). In production, you'd replace the mock endpoint URL with:
  - PagerDuty Events API v2
  - Slack incoming webhook
  - Custom alert aggregation service
"""

import logging
from abc import ABC, abstractmethod

import httpx

from app.models.schemas import SignalIn

logger = logging.getLogger(__name__)


async def send_mock_alert(alert_type: str, signal: SignalIn, work_item_id: str):
    """
    Fire an HTTP webhook to simulate real alert dispatch.

    WHY HTTP instead of logging:
    Logging says "we would have alerted." HTTP proves the system CAN dispatch
    alerts over the network, which is what a real PagerDuty/Slack integration
    would do. The mock endpoint validates the full alert pipeline.
    """
    payload = {
        "type": alert_type,
        "component_id": signal.component_id,
        "severity": signal.severity.value if hasattr(signal.severity, 'value') else signal.severity,
        "work_item_id": work_item_id,
        "message": signal.error_message,
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "http://backend:8000/mock-alert",
                json=payload,
                timeout=2.0,
            )
    except Exception as e:
        # Alert failure should NOT block signal processing.
        # Log and continue — the work item is already created.
        logger.error("Failed to send mock alert: %s", e)


class AlertStrategy(ABC):
    """Base class for component-specific alert escalation policies."""

    @abstractmethod
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        raise NotImplementedError


class RDBMSAlertStrategy(AlertStrategy):
    """P0 — Database failures get immediate on-call page."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning(
            "[ALERT] P0 RDBMS page for %s, work_item=%s",
            signal.component_id, work_item_id,
        )
        await send_mock_alert("RDBMS_PAGE", signal, work_item_id)


class CacheAlertStrategy(AlertStrategy):
    """P2 — Cache failures are performance degradation, not outages."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning(
            "[ALERT] P2 cache warning for %s, work_item=%s",
            signal.component_id, work_item_id,
        )
        await send_mock_alert("CACHE_WARNING", signal, work_item_id)


class APIAlertStrategy(AlertStrategy):
    """P1 — API failures affect users but may have client-side retries."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning(
            "[ALERT] P1 API incident for %s, work_item=%s",
            signal.component_id, work_item_id,
        )
        await send_mock_alert("API_INCIDENT", signal, work_item_id)


class QueueAlertStrategy(AlertStrategy):
    """P1 — Queue failures can cause data pipeline delays."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning(
            "[ALERT] P1 queue incident for %s, work_item=%s",
            signal.component_id, work_item_id,
        )
        await send_mock_alert("QUEUE_INCIDENT", signal, work_item_id)


class MCPAlertStrategy(AlertStrategy):
    """P0 — Control plane failures are critical infrastructure events."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning(
            "[ALERT] P0 MCP page for %s, work_item=%s",
            signal.component_id, work_item_id,
        )
        await send_mock_alert("MCP_PAGE", signal, work_item_id)


class NoOpAlertStrategy(AlertStrategy):
    """Fallback — unknown component types log but don't escalate."""

    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.info(
            "[ALERT] No escalation policy for %s, work_item=%s",
            signal.component_type, work_item_id,
        )


def get_alert_strategy(component_type: str) -> AlertStrategy:
    """
    Factory function — maps component_type to its alert strategy.

    WHY a dictionary (not a class registry):
    For 6 component types, a simple dictionary is clearer than a metaclass
    or decorator-based registry. If the number grows beyond ~15, switch to
    a plugin architecture with auto-discovery.
    """
    strategies: dict[str, AlertStrategy] = {
        "rdbms": RDBMSAlertStrategy(),
        "cache": CacheAlertStrategy(),
        "api": APIAlertStrategy(),
        "queue": QueueAlertStrategy(),
        "mcp": MCPAlertStrategy(),
    }
    return strategies.get(component_type, NoOpAlertStrategy())
