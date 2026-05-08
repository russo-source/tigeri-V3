from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext, BaseAgent
from tigeri.agents.staffing.schemas import (
    DemandWindow,
    Roster,
    Shift,
    StaffingInput,
    StaffingOutput,
    StaffMember,
)
from tigeri.core.ids import new_id


class StaffingAgent(BaseAgent):
    agent_id = "staffing_agent"

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: StaffingInput,
    ) -> StaffingOutput:
        roster_id = new_id("ros")

        # Capability 1: generate_roster
        shifts, gap_count = await self._generate(session, ctx.tenant_id, request)
        await self.audit(
            session,
            ctx,
            "generate_roster",
            roster_id,
            "OK",
            {"shifts": len(shifts), "gaps": gap_count},
        )

        # Capability 2: publish_roster
        await self.audit(session, ctx, "publish_roster", roster_id, "OK", None)

        # Capability 3: detect_gap
        gaps = [s for s in shifts if s.coverage_status == "OPEN"]
        await self.audit(
            session, ctx, "detect_gap", roster_id, "OK", {"gap_count": len(gaps)}
        )

        # Capability 4: source_cover
        # Don't double-book: exclude staff already assigned to a primary shift
        # in the same window. Without this filter the cover step happily
        # reassigns u1 (already on shift 1) to fill the OPEN shift in the same
        # interval, producing a roster where one person works two simultaneous
        # shifts.
        already_on_shift = {s.assignee_id for s in shifts if s.coverage_status == "ASSIGNED"}
        cover_assignments: dict[str, str] = {}
        if gaps:
            candidates = await self._cover_candidates(
                session, ctx.tenant_id, request.venue_ids, exclude=already_on_shift
            )
            for shift in gaps:
                cand = candidates.pop(shift.venue_id, None) if candidates else None
                if cand is not None:
                    cover_assignments[shift.shift_id] = cand
        await self.audit(
            session,
            ctx,
            "source_cover",
            roster_id,
            "OK",
            {"covered": len(cover_assignments)},
        )

        # Capability 5: confirm_cover
        for shift in shifts:
            if shift.shift_id in cover_assignments:
                shift.assignee_id = cover_assignments[shift.shift_id]
                shift.coverage_status = "ASSIGNED"
        gap_count = sum(1 for s in shifts if s.coverage_status == "OPEN")
        await self.audit(
            session,
            ctx,
            "confirm_cover",
            roster_id,
            "OK",
            {"remaining_gaps": gap_count},
        )

        # Capability 6: notify
        await self.audit(
            session,
            ctx,
            "notify",
            roster_id,
            "OK",
            {"venues_notified": len(set(s.venue_id for s in shifts))},
        )

        row = Roster(
            id=roster_id,
            tenant_id=ctx.tenant_id,
            period_start=request.period_start.astimezone(UTC)
            if request.period_start.tzinfo
            else request.period_start.replace(tzinfo=UTC),
            period_end=request.period_end.astimezone(UTC)
            if request.period_end.tzinfo
            else request.period_end.replace(tzinfo=UTC),
            open_gap_count=gap_count,
            shifts_json={"items": [s.model_dump(mode="json") for s in shifts]},
        )
        session.add(row)

        return StaffingOutput(
            tenant_id=ctx.tenant_id,
            roster_id=roster_id,
            shifts=shifts,
            open_gap_count=gap_count,
        )

    async def _generate(
        self, session: AsyncSession, tenant_id: str, request: StaffingInput
    ) -> tuple[list[Shift], int]:
        staff_pool = await self._available_staff(session, tenant_id, request.venue_ids)
        venue_for: dict[str, list[StaffMember]] = {vid: [] for vid in request.venue_ids}
        for member in staff_pool:
            if member.venue_id and member.venue_id in venue_for:
                venue_for[member.venue_id].append(member)

        shifts: list[Shift] = []
        gap_count = 0
        for window in request.demand_curve:
            for venue_id in request.venue_ids:
                pool = venue_for.get(venue_id, [])
                for slot in range(window.headcount_required):
                    if slot < len(pool):
                        member = pool[slot]
                        shifts.append(
                            Shift(
                                shift_id=new_id("sft"),
                                venue_id=venue_id,
                                start=window.interval_start,
                                end=window.interval_end,
                                assignee_id=member.id,
                                coverage_status="ASSIGNED",
                            )
                        )
                    else:
                        gap_count += 1
                        shifts.append(
                            Shift(
                                shift_id=new_id("sft"),
                                venue_id=venue_id,
                                start=window.interval_start,
                                end=window.interval_end,
                                assignee_id="",
                                coverage_status="OPEN",
                            )
                        )
        return shifts, gap_count

    @staticmethod
    async def _available_staff(
        session: AsyncSession, tenant_id: str, venue_ids: list[str]
    ) -> list[StaffMember]:
        rows = await session.scalars(
            select(StaffMember).where(
                StaffMember.tenant_id == tenant_id,
                StaffMember.available.is_(True),
                StaffMember.venue_id.in_(venue_ids),
            )
        )
        return list(rows)

    async def _cover_candidates(
        self,
        session: AsyncSession,
        tenant_id: str,
        venue_ids: list[str],
        exclude: set[str] | None = None,
    ) -> dict[str, str] | None:
        rows = await session.scalars(
            select(StaffMember).where(
                StaffMember.tenant_id == tenant_id,
                StaffMember.available.is_(True),
                StaffMember.venue_id.in_(venue_ids),
            )
        )
        skip = exclude or set()
        # Pick at most one cover candidate per venue, excluding anyone already
        # rostered onto a primary shift in this window.
        per_venue: dict[str, str] = {}
        for r in rows:
            if r.id in skip:
                continue
            per_venue.setdefault(r.venue_id or "", r.id)
        return per_venue


_ = (Any, datetime, DemandWindow)
