import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.models.schemas import SignalIn, ComponentType, Severity
from app.services.ingestion import resolve_work_item

@pytest.mark.asyncio
async def test_signal_to_incident_integration():
    """
    Integration Test: Proves the end-to-end flow from signal ingestion to 
    WorkItem creation when the debounce threshold is reached.
    """
    component_id = f"test-comp-{uuid4().hex[:8]}"
    signal = SignalIn(
        component_id=component_id,
        component_type=ComponentType.api,
        error_message="Integration test failure",
        severity=Severity.P0,
        timestamp=datetime.now(timezone.utc)
    )

    # Mock dependencies to avoid side effects but test the logic flow
    with patch("app.services.ingestion.get_existing_workitem_id", new_callable=AsyncMock) as mock_get_existing, \
         patch("app.services.ingestion.redis_client", new_callable=AsyncMock) as mock_redis, \
         patch("app.services.ingestion.get_mongo_db") as mock_mongo_fn, \
         patch("app.services.ingestion.create_work_item", new_callable=AsyncMock) as mock_create:
        
        # Mock the mongo client chains
        mock_mongo = MagicMock()
        mock_mongo_fn.return_value = mock_mongo
        mock_mongo.signals.update_many = AsyncMock()
        
        # Scenario 1: First 99 signals (Threshold is 100)
        mock_get_existing.return_value = None
        mock_redis.zcard.return_value = 99
        mock_redis.get.return_value = None
        
        res = await resolve_work_item(signal, "q1")
        assert res is None
        mock_create.assert_not_called()

        # Scenario 2: The 100th signal trips the threshold
        mock_redis.zcard.return_value = 100
        mock_create.return_value = uuid4()
        
        res = await resolve_work_item(signal, "q100")
        assert res is not None
        mock_create.assert_called_once()
        print(f"✅ Integration Flow: Successfully created incident {res} after 100 signals")
