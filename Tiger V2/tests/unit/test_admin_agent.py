import pytest
from sqlalchemy import select

from tigeri.agents.admin.agent import AdminAgent, TemplateNotFoundError
from tigeri.agents.admin.schemas import AdminInput, AdminSubject
from tigeri.agents.base import AgentRunContext
from tigeri.audit.record import AuditRecord


@pytest.mark.asyncio
async def test_onboarding_template_runs_and_emits_audit_chain(session):
    agent = AdminAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_a", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        AdminInput(
            tenant_id="tnt_a",
            workflow_template_id="employee_onboarding_v1",
            subject=AdminSubject(type="EMPLOYEE", id="emp_42"),
            initiator_id="hr_lead",
            context={"manager_id": "mgr_99"},
        ),
    )
    await session.commit()

    assert out.status == "COMPLETED"
    assert "offer_letter.pdf" in out.documents_generated
    recipients = {c.recipient_id for c in out.communications_sent}
    assert "emp_42" in recipients
    assert "mgr_99" in recipients

    rows = (
        await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ).all()
    actions = [r.action for r in rows]
    assert actions[0] == "render_form"
    assert "onboard" in actions
    assert actions[-2] == "generate_doc"
    assert actions[-1] == "send_comm"


@pytest.mark.asyncio
async def test_unknown_template_raises_and_audits(session):
    agent = AdminAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_b", actor="api")
    with pytest.raises(TemplateNotFoundError):
        await agent.invoke(
            session,
            ctx,
            AdminInput(
                tenant_id="tnt_b",
                workflow_template_id="does_not_exist",
                subject=AdminSubject(type="CLIENT", id="c_1"),
                initiator_id="ops",
            ),
        )
    await session.commit()

    rows = (
        await session.scalars(
            select(AuditRecord).where(AuditRecord.trace_id == ctx.trace_id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].outcome == "FAILED"
