from sqlalchemy import select

from tigeri.audit.record import AuditRecord
from tigeri.audit.sink_local import AuditEvent, emit


async def test_emit_writes_append_only_record(session):
    event = AuditEvent(
        actor="invoice_agent:api",
        action="post",
        target_resource="inv_xyz",
        tenant_id="tnt_1",
        outcome="POSTED",
        trace_id="trace_abc",
        payload={"posting_reference": "gl_999"},
    )
    record = await emit(session, event)
    await session.commit()

    rows = (await session.scalars(select(AuditRecord))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == record.id
    assert row.action == "post"
    assert row.tenant_id == "tnt_1"
    assert row.outcome == "POSTED"
    assert row.trace_id == "trace_abc"
    # Compliance & Audit Agent (Priority 12) not yet live
    assert row.chain_position is None
    assert row.backfilled_at is None
    assert "gl_999" in (row.payload_json or "")
