from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.invoice.agent import InvoiceAgent
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
async def test_invoice_e2e_emits_six_audit_records(session):
    agent = InvoiceAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_acme", actor="api")
    request = InvoiceInput(
        tenant_id="tnt_acme",
        source="UPLOAD",
        document=InvoiceDocument(media_type="text/plain", content_ref=f"inline:{SAMPLE}"),
        received_at=datetime.now(UTC),
    )

    output = await agent.invoke(session, ctx, request)
    await session.commit()

    assert output.validation_status == "VALID"
    assert output.approval_status == "APPROVED"
    assert output.posting_status == "POSTED"
    assert output.posting_reference.startswith("gl_")
    assert output.vendor_name == "Globex Logistics"
    assert output.currency == "AUD"

    # Section 5.4: every agent action emits one audit record. Six capabilities → six rows.
    rows = (
        await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ).all()
    actions = [r.action for r in rows]
    assert actions == ["capture", "extract", "validate", "route", "post", "emit_event"]
    for r in rows:
        assert r.tenant_id == "tnt_acme"
        assert r.actor.startswith("invoice_agent:")
        # Compliance & Audit Agent (Priority 12) not yet live → fields stay NULL
        assert r.chain_position is None
        assert r.backfilled_at is None
