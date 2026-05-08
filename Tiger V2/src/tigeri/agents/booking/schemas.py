from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class TimeWindow(BaseModel):
    start: datetime
    end: datetime


class Participant(BaseModel):
    id: str
    # role defaults to ATTENDEE so the orchestrator (and ad-hoc API callers)
    # don't have to explicitly attach a role to every guest. Demo prompts
    # like 'book a meeting with russo@tigeri.ai' previously 422'd because
    # the model didn't supply a role for an obvious attendee.
    role: str = "ATTENDEE"


class BookingInput(BaseModel):
    """Section 6.5.3 input schema."""

    tenant_id: str
    booking_type: Literal["RESERVATION", "INSPECTION", "CLASS", "MEETING"]
    requested_window: TimeWindow
    participants: list[Participant]
    venue_id: str


class BookingOutput(BaseModel):
    """Section 6.5.4 output schema."""

    tenant_id: str
    booking_id: str
    confirmed_window: TimeWindow
    venue_id: str
    status: Literal["CONFIRMED", "WAITLISTED", "DECLINED"]
    notifications_dispatched: int


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    venue_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    booking_type: Mapped[str] = mapped_column(String(32), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    notifications_dispatched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
