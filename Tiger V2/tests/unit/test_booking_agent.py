from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.booking.agent import BookingAgent
from tigeri.agents.booking.schemas import (
    BookingInput,
    Booking,
    Participant,
    TimeWindow,
)
from tigeri.audit.record import AuditRecord


@pytest.mark.asyncio
async def test_booking_confirms_when_no_conflict(session):
    agent = BookingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_b", actor="api")
    start = datetime.now(UTC).replace(microsecond=0)
    out = await agent.invoke(
        session,
        ctx,
        BookingInput(
            tenant_id="tnt_b",
            booking_type="MEETING",
            requested_window=TimeWindow(start=start, end=start + timedelta(hours=1)),
            participants=[
                Participant(id="u1", role="organiser"),
                Participant(id="u2", role="attendee"),
            ],
            venue_id="v_room_a",
        ),
    )
    await session.commit()
    assert out.status == "CONFIRMED"
    assert out.notifications_dispatched == 2

    actions = [
        r.action
        for r in await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ]
    assert actions == [
        "accept_request",
        "resolve_availability",
        "confirm",
        "notify",
        "reschedule_or_cancel",
        "surface_utilisation",
    ]


@pytest.mark.asyncio
async def test_booking_declines_on_conflict(session):
    start = datetime.now(UTC).replace(microsecond=0)
    session.add(
        Booking(
            id="bkg_existing",
            tenant_id="tnt_c",
            venue_id="v_x",
            booking_type="MEETING",
            start_at=start,
            end_at=start + timedelta(hours=2),
            status="CONFIRMED",
            notifications_dispatched=1,
        )
    )
    await session.flush()

    agent = BookingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_c", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        BookingInput(
            tenant_id="tnt_c",
            booking_type="MEETING",
            requested_window=TimeWindow(start=start, end=start + timedelta(hours=1)),
            participants=[Participant(id="u1", role="organiser")],
            venue_id="v_x",
        ),
    )
    await session.commit()
    assert out.status == "DECLINED"
    assert out.notifications_dispatched == 0
