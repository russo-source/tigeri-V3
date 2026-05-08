from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.staffing.agent import StaffingAgent
from tigeri.agents.staffing.schemas import (
    DemandWindow,
    Roster,
    StaffingInput,
    StaffMember,
)
from tigeri.audit.record import AuditRecord


@pytest.mark.asyncio
async def test_roster_generated_with_assignments_and_gaps(session):
    # Two staff at venue v1; demand needs three → 1 gap
    for sid in ("u1", "u2"):
        session.add(
            StaffMember(
                id=sid,
                tenant_id="tnt_s",
                name=sid.upper(),
                skills_json={},
                venue_id="v1",
                available=True,
            )
        )
    await session.flush()

    agent = StaffingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_s", actor="api")
    start = datetime.now(UTC)
    out = await agent.invoke(
        session,
        ctx,
        StaffingInput(
            tenant_id="tnt_s",
            venue_ids=["v1"],
            period_start=start,
            period_end=start + timedelta(hours=8),
            demand_curve=[
                DemandWindow(
                    interval_start=start,
                    interval_end=start + timedelta(hours=8),
                    headcount_required=3,
                )
            ],
        ),
    )
    await session.commit()

    assert len(out.shifts) == 3
    assigned = [s for s in out.shifts if s.coverage_status == "ASSIGNED"]
    assert len(assigned) == 2
    assert out.open_gap_count == 1

    persisted = await session.scalar(select(Roster).where(Roster.id == out.roster_id))
    assert persisted is not None
    assert persisted.open_gap_count == 1

    actions = [
        r.action
        for r in await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ]
    assert actions == [
        "generate_roster",
        "publish_roster",
        "detect_gap",
        "source_cover",
        "confirm_cover",
        "notify",
    ]
