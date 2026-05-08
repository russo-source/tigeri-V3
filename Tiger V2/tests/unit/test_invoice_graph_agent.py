from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.invoice.graph_agent import InvoiceGraphAgent
from tigeri.agents.invoice.schemas import InvoiceDocument, InvoiceInput
from tigeri.audit.record import AuditRecord


SAMPLE = (
    "vendor: Globex Logistics\n"
    "currency: AUD\n"
    "total: 1500.00\n"
    "tax: 150.00\n"
    "invoice: INV-7788\n"
    "due: 2026-06-15\n"
)


@pytest.mark.asyncio
async def test_invoice_graph_runs_and_emits_six_audit_records(session):
    agent = InvoiceGraphAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_g", actor="api")
    request = InvoiceInput(
        tenant_id="tnt_g",
        source="UPLOAD",
        document=InvoiceDocument(media_type="text/plain", content_ref=f"inline:{SAMPLE}"),
        received_at=datetime.now(UTC),
    )
    out = await agent.invoke(
        session,
        ctx,
        request,
        session_id="s_alpha",
        user_id="usr_zoe",
    )
    await session.commit()
    assert out.validation_status == "VALID"
    assert out.posting_status == "POSTED"

    actions = [
        r.action
        for r in await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ]
    assert actions == ["capture", "extract", "validate", "route", "post", "emit_event"]


@pytest.mark.asyncio
async def test_session_memory_persists_invocation_count_and_behaviour(session):
    agent = InvoiceGraphAgent()
    base_request = lambda hash_seed: InvoiceInput(  # noqa: E731
        tenant_id="tnt_mem",
        source="UPLOAD",
        document=InvoiceDocument(
            media_type="text/plain",
            content_ref=f"inline:{SAMPLE}\n# seed:{hash_seed}",
        ),
        received_at=datetime.now(UTC),
    )

    ctx_a = AgentRunContext.new(tenant_id="tnt_mem", actor="api")
    await agent.invoke(
        session, ctx_a, base_request("a"), session_id="s_persist", user_id="usr_x"
    )
    ctx_b = AgentRunContext.new(tenant_id="tnt_mem", actor="api")
    await agent.invoke(
        session, ctx_b, base_request("b"), session_id="s_persist", user_id="usr_x"
    )
    await session.commit()

    # Inspect the graph's checkpointed session memory directly.
    from tigeri.graph.checkpointer import thread_id_for

    config = {"configurable": {"thread_id": thread_id_for("tnt_mem", "usr_x", "s_persist")}}
    state = await agent._compiled.aget_state(config)
    assert state.values["session"]["invocations"] == 2
    assert state.values["session"]["behaviour"]["last_validation"] == "VALID"
    assert state.values["session"]["behaviour"]["rejection_streak"] == 0
