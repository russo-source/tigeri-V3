from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.expense.agent import ExpenseAgent
from tigeri.agents.expense.schemas import CardTransaction, Expense, ExpenseInput
from tigeri.audit.record import AuditRecord


SAMPLE = (
    "vendor: Qantas Airways\n"
    "currency: AUD\n"
    "total: 480.00\n"
    "tax: 48.00\n"
    "invoice: RCT-AB-12\n"
)


@pytest.mark.asyncio
async def test_expense_e2e_emits_six_audit_records(session):
    agent = ExpenseAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_e", actor="api")
    request = ExpenseInput(
        tenant_id="tnt_e",
        submitter_id="usr_alice",
        image_ref=f"inline:{SAMPLE}",
        captured_at=datetime.now(UTC),
    )
    out = await agent.invoke(session, ctx, request)
    await session.commit()

    assert out.merchant == "Qantas Airways"
    assert out.category == "TRAVEL"
    assert out.policy_status in {"NEEDS_REVIEW", "OUT_OF_POLICY"}  # 480 > review threshold 250
    assert out.reconciliation_status == "UNMATCHED"

    rows = (
        await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ).all()
    assert [r.action for r in rows] == [
        "scan",
        "extract",
        "categorise",
        "policy_check",
        "reconcile",
        "submit",
    ]


@pytest.mark.asyncio
async def test_expense_matches_card_txn(session):
    captured_at = datetime.now(UTC)
    session.add(
        CardTransaction(
            id="ctx_1",
            tenant_id="tnt_m",
            merchant="Qantas Airways",
            amount=Decimal("480.00"),
            currency="AUD",
            occurred_at=captured_at,
        )
    )
    await session.flush()

    agent = ExpenseAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_m", actor="api")
    request = ExpenseInput(
        tenant_id="tnt_m",
        submitter_id="usr_bob",
        image_ref=f"inline:{SAMPLE}",
        captured_at=captured_at,
    )
    out = await agent.invoke(session, ctx, request)
    assert out.reconciliation_status == "MATCHED"
    assert out.matched_card_txn_id == "ctx_1"

    persisted = await session.scalar(select(Expense).where(Expense.id == out.expense_id))
    assert persisted is not None
    assert persisted.matched_card_txn_id == "ctx_1"
