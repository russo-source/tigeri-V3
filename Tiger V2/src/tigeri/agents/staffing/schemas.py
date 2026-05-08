from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class DemandWindow(BaseModel):
    interval_start: datetime
    interval_end: datetime
    headcount_required: int
    skills_required: list[str] = []


class StaffingInput(BaseModel):
    """Section 6.4.3 input schema."""

    tenant_id: str
    venue_ids: list[str]
    period_start: datetime
    period_end: datetime
    demand_curve: list[DemandWindow]


class Shift(BaseModel):
    shift_id: str
    venue_id: str
    start: datetime
    end: datetime
    assignee_id: str
    coverage_status: Literal["ASSIGNED", "OPEN", "COVER_PENDING"]


class StaffingOutput(BaseModel):
    """Section 6.4.4 output schema."""

    tenant_id: str
    roster_id: str
    shifts: list[Shift]
    open_gap_count: int


# Persistence -------------------------------------------------------------


class Roster(Base):
    __tablename__ = "rosters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shifts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class StaffMember(Base):
    """Stub HRIS view for slice 2 cover sourcing."""

    __tablename__ = "staff_members"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    skills_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    venue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available: Mapped[bool] = mapped_column(default=True)
