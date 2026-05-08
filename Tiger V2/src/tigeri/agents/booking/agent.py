from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext, BaseAgent
from tigeri.agents.booking.schemas import (
    Booking,
    BookingInput,
    BookingOutput,
    TimeWindow,
)
from tigeri.core.concurrency import advisory_xact_lock, booking_lock_key
from tigeri.core.ids import new_id


class BookingAgent(BaseAgent):
    agent_id = "booking_agent"

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: BookingInput,
    ) -> BookingOutput:
        booking_id = new_id("bkg")

        # Capability 1: accept_request
        await self.audit(
            session,
            ctx,
            "accept_request",
            booking_id,
            "OK",
            {"booking_type": request.booking_type, "venue_id": request.venue_id},
        )

        # Capability 2: resolve_availability
        start_at = (
            request.requested_window.start.astimezone(UTC)
            if request.requested_window.start.tzinfo
            else request.requested_window.start.replace(tzinfo=UTC)
        )
        end_at = (
            request.requested_window.end.astimezone(UTC)
            if request.requested_window.end.tzinfo
            else request.requested_window.end.replace(tzinfo=UTC)
        )
        if end_at <= start_at:
            raise ValueError(
                f"requested_window must have end > start (got start={start_at}, end={end_at})"
            )

        # Serialise availability checks per (tenant, venue). Two concurrent
        # requests for the same venue+window used to both see no conflict and
        # both persist CONFIRMED rows; this lock holds until the new row is
        # flushed at the end of the transaction.
        await advisory_xact_lock(
            session, booking_lock_key(ctx.tenant_id, request.venue_id)
        )

        conflict = await session.scalar(
            select(Booking).where(
                Booking.tenant_id == ctx.tenant_id,
                Booking.venue_id == request.venue_id,
                Booking.status == "CONFIRMED",
                Booking.start_at < end_at,
                Booking.end_at > start_at,
            )
        )
        status_value = "DECLINED" if conflict is not None else "CONFIRMED"
        await self.audit(
            session,
            ctx,
            "resolve_availability",
            booking_id,
            status_value,
            {"conflict_with": conflict.id if conflict else None},
        )

        # Capability 3: confirm
        row = Booking(
            id=booking_id,
            tenant_id=ctx.tenant_id,
            venue_id=request.venue_id,
            booking_type=request.booking_type,
            start_at=start_at,
            end_at=end_at,
            status=status_value,
            notifications_dispatched=len(request.participants) if status_value == "CONFIRMED" else 0,
        )
        session.add(row)
        await self.audit(session, ctx, "confirm", booking_id, status_value, None)

        # Capability 4: notify
        notifications = len(request.participants) if status_value == "CONFIRMED" else 0
        await self.audit(
            session, ctx, "notify", booking_id, "OK", {"count": notifications}
        )

        # Capability 5: reschedule_or_cancel (no-op on initial create)
        await self.audit(
            session, ctx, "reschedule_or_cancel", booking_id, "NOOP", None
        )

        # Capability 6: surface_utilisation
        await self.audit(
            session,
            ctx,
            "surface_utilisation",
            booking_id,
            "OK",
            {"venue_id": request.venue_id},
        )

        return BookingOutput(
            tenant_id=ctx.tenant_id,
            booking_id=booking_id,
            confirmed_window=TimeWindow(start=start_at, end=end_at),
            venue_id=request.venue_id,
            status=status_value,  # type: ignore[arg-type]
            notifications_dispatched=notifications,
        )
