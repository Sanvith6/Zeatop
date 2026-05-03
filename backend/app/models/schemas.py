from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComponentType(StrEnum):
    cache = "cache"
    rdbms = "rdbms"
    api = "api"
    queue = "queue"
    nosql = "nosql"
    mcp = "mcp"


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class WorkItemStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RootCauseCategory(StrEnum):
    Infrastructure = "Infrastructure"
    CodeDeployment = "Code Deployment"
    ConfigurationChange = "Configuration Change"
    ExternalDependency = "External Dependency"
    Unknown = "Unknown"


class SignalIn(BaseModel):
    component_id: str = Field(min_length=1, max_length=128)
    component_type: ComponentType
    error_message: str = Field(min_length=1, max_length=2000)
    severity: Severity
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SignalAccepted(BaseModel):
    """Response returned on successful signal ingestion."""
    status: str
    event_id: str


class TransitionRequest(BaseModel):
    new_state: WorkItemStatus


class RCARequest(BaseModel):
    incident_start: datetime
    incident_end: datetime
    root_cause_category: RootCauseCategory
    fix_applied: str = Field(min_length=1)
    prevention_steps: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "RCARequest":
        if self.incident_end <= self.incident_start:
            raise ValueError("incident_end must be after incident_start")
        return self


class RCAResponse(BaseModel):
    id: UUID
    work_item_id: UUID
    incident_start: datetime
    incident_end: datetime
    root_cause_category: str
    fix_applied: str
    prevention_steps: str
    submitted_at: datetime
    mttr_minutes: float
    model_config = ConfigDict(from_attributes=True)


class StatusHistoryResponse(BaseModel):
    from_status: str | None
    to_status: str
    changed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkItemResponse(BaseModel):
    id: UUID
    component_id: str
    component_type: str
    severity: str
    status: str
    signal_count: int
    created_at: datetime
    updated_at: datetime
    rca_id: UUID | None = None
    mttr_minutes: float | None = None
    model_config = ConfigDict(from_attributes=True)


class WorkItemDetailResponse(WorkItemResponse):
    signals: list[dict[str, Any]]
    timeline: list[StatusHistoryResponse]
    rca: RCAResponse | None = None


class AISuggestionResponse(BaseModel):
    root_cause_category: RootCauseCategory
    fix_applied: str
    prevention_steps: str
