import logging
from abc import ABC, abstractmethod

from app.models.schemas import SignalIn

logger = logging.getLogger(__name__)


class AlertStrategy(ABC):
    @abstractmethod
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        raise NotImplementedError


class RDBMSAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning("[ALERT] P0 RDBMS page for %s, work_item=%s", signal.component_id, work_item_id)


class CacheAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning("[ALERT] P2 cache warning for %s, work_item=%s", signal.component_id, work_item_id)


class APIAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning("[ALERT] P1 API incident for %s, work_item=%s", signal.component_id, work_item_id)


class QueueAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning("[ALERT] P1 queue incident for %s, work_item=%s", signal.component_id, work_item_id)


class MCPAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.warning("[ALERT] P0 MCP page for %s, work_item=%s", signal.component_id, work_item_id)


class NoOpAlertStrategy(AlertStrategy):
    async def alert(self, signal: SignalIn, work_item_id: str) -> None:
        logger.info("[ALERT] No escalation policy for %s, work_item=%s", signal.component_type, work_item_id)


def get_alert_strategy(component_type: str) -> AlertStrategy:
    strategies: dict[str, AlertStrategy] = {
        "rdbms": RDBMSAlertStrategy(),
        "cache": CacheAlertStrategy(),
        "api": APIAlertStrategy(),
        "queue": QueueAlertStrategy(),
        "mcp": MCPAlertStrategy(),
    }
    return strategies.get(component_type, NoOpAlertStrategy())
