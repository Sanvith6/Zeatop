from uuid import UUID

from fastapi import APIRouter, Depends

from app.models.schemas import AISuggestionResponse, RCARequest, RCAResponse, TransitionRequest, WorkItemDetailResponse, WorkItemResponse
from app.security import require_auth
from app.services.workitems import get_workitem_detail, list_workitems, submit_rca, suggest_ai_rca, transition_workitem

router = APIRouter(prefix="/api/workitems", tags=["workitems"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[WorkItemResponse])
async def get_workitems(status: str | None = None) -> list[dict]:
    return await list_workitems(status=status)


@router.get("/{work_item_id}", response_model=WorkItemDetailResponse)
async def get_workitem(work_item_id: UUID) -> dict:
    return await get_workitem_detail(work_item_id)


@router.patch("/{work_item_id}/transition", response_model=WorkItemResponse)
async def transition(work_item_id: UUID, payload: TransitionRequest) -> dict:
    return await transition_workitem(work_item_id, payload.new_state.value)


@router.post("/{work_item_id}/rca", response_model=RCAResponse)
async def create_rca(work_item_id: UUID, payload: RCARequest) -> dict:
    return await submit_rca(work_item_id, payload)


@router.post("/{work_item_id}/suggest-rca", response_model=AISuggestionResponse)
async def suggest_rca(work_item_id: UUID) -> dict:
    return await suggest_ai_rca(work_item_id)
