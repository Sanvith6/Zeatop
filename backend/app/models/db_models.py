import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkItem(Base):
    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    component_id: Mapped[str] = mapped_column(String, index=True)
    component_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    signal_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    rca_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rca.id"), nullable=True)
    mttr_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    rca: Mapped["RCA | None"] = relationship("RCA", foreign_keys=[rca_id], post_update=True)
    history: Mapped[list["WorkItemStatusHistory"]] = relationship(
        "WorkItemStatusHistory", cascade="all, delete-orphan", order_by="WorkItemStatusHistory.changed_at"
    )


class RCA(Base):
    __tablename__ = "rca"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    incident_start: Mapped[datetime] = mapped_column(DateTime)
    incident_end: Mapped[datetime] = mapped_column(DateTime)
    root_cause_category: Mapped[str] = mapped_column(String)
    fix_applied: Mapped[str] = mapped_column(Text)
    prevention_steps: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorkItemStatusHistory(Base):
    __tablename__ = "work_item_status_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
