"""Unit tests for Phase 1 Priority 6, 7, 8 agents (LangGraph-native)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from tigeri.agents.base import AgentRunContext
from tigeri.agents.client_onboarding.agent import ClientOnboardingAgent
from tigeri.agents.client_onboarding.schemas import (
    COInput,
    ClientRecord,
    Onboarding,
    PrimaryContact,
)
from tigeri.agents.contract_management.agent import ContractManagementAgent
from tigeri.agents.contract_management.schemas import Contract, ContractInput
from tigeri.agents.financial_reporting.agent import FinancialReportingAgent
from tigeri.agents.financial_reporting.schemas import FRInput, FinancialReport, Period
from tigeri.agents.invoice.schemas import Invoice
from tigeri.audit.record import AuditRecord


@pytest.mark.asyncio
async def test_financial_reporting_rolls_up_invoices(session):
    # Seed two posted invoices in the period
    now = datetime.now(UTC)
    for i, amt in enumerate(["100.00", "250.00"]):
        session.add(
            Invoice(
                id=f"inv_seed_{i}",
                tenant_id="tnt_fr",
                vendor_name="Vendor",
                currency="USD",
                amount_total=Decimal(amt),
                tax_total=Decimal("0"),
                line_items_json={},
                validation_status="VALID",
                approval_status="APPROVED",
                posting_status="POSTED",
                posting_reference=f"gl_{i}",
                document_hash=f"h{i}",
                received_at=now - timedelta(days=1),
            )
        )
    await session.flush()

    agent = FinancialReportingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_fr", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        FRInput(
            tenant_id="tnt_fr",
            report_type="PNL",
            period=Period(start=now - timedelta(days=7), end=now + timedelta(days=1)),
        ),
    )
    await session.commit()
    assert out.report_type == "PNL"
    revenue = next(k for k in out.kpis if k.name == "revenue_total")
    assert revenue.value == Decimal("350.00")
    net = next(k for k in out.kpis if k.name == "net_income")
    assert net.value == Decimal("350.00")  # no expenses seeded

    persisted = await session.scalar(
        select(FinancialReport).where(FinancialReport.id == out.report_id)
    )
    assert persisted is not None
    assert persisted.revenue_total == Decimal("350.00")

    actions = [
        r.action
        for r in await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ]
    assert actions == [
        "pull_balances",
        "compute_pnl",
        "compute_cashflow",
        "compute_kpis",
        "render",
        "deliver",
    ]


SAMPLE_CONTRACT = (
    "counterparty: Acme Pty Ltd\n"
    "effective: 2026-01-01\n"
    "expiry: 2027-01-01\n"
    "auto_renewal: false\n"
    "value: 12000.00\n"
    "currency: AUD\n"
    "payment_terms: NET30\n"
    "termination_notice: 90 days\n"
)


@pytest.mark.asyncio
async def test_contract_management_extracts_and_persists(session):
    agent = ContractManagementAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_ct", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        ContractInput(
            tenant_id="tnt_ct",
            document_ref=f"inline:{SAMPLE_CONTRACT}",
            uploader_id="usr_legal",
            counterparty_hint="Acme",
        ),
    )
    await session.commit()
    assert out.counterparty == "Acme Pty Ltd"
    assert out.lifecycle_state in {"ACTIVE", "EXPIRING"}
    term_names = {t.term for t in out.key_terms}
    assert "payment_terms" in term_names
    persisted = await session.scalar(select(Contract).where(Contract.id == out.contract_id))
    assert persisted is not None

    actions = [
        r.action
        for r in await session.scalars(
            select(AuditRecord)
            .where(AuditRecord.trace_id == ctx.trace_id)
            .order_by(AuditRecord.timestamp_utc)
        )
    ]
    assert actions == [
        "ingest",
        "extract_terms",
        "track",
        "schedule_alerts",
        "surface_obligations",
        "render_register",
    ]


@pytest.mark.asyncio
async def test_client_onboarding_passes_kyc_when_clean(session):
    agent = ClientOnboardingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_co", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        COInput(
            tenant_id="tnt_co",
            client_record=ClientRecord(
                legal_name="Globex Logistics",
                registration_id="ABN-99-clean",
                primary_contact=PrimaryContact(
                    name="Sam Rider", email="sam@globex.test"
                ),
            ),
            signed_contract_ref="s3://contracts/sig-1.pdf",
        ),
    )
    await session.commit()
    assert out.kyc_status == "PASS"
    assert out.kyb_status == "PASS"
    assert out.project_plan_ref.startswith("db://project_plans/")
    assert out.kickoff_meeting_id.startswith("mtg_")

    persisted = await session.scalar(select(Onboarding).where(Onboarding.id == out.onboarding_id))
    assert persisted is not None
    assert persisted.client_legal_name == "Globex Logistics"


@pytest.mark.asyncio
async def test_client_onboarding_marks_review_when_flagged(session):
    agent = ClientOnboardingAgent()
    ctx = AgentRunContext.new(tenant_id="tnt_co2", actor="api")
    out = await agent.invoke(
        session,
        ctx,
        COInput(
            tenant_id="tnt_co2",
            client_record=ClientRecord(
                legal_name="Suspect Co",
                registration_id="needs-review-please",
                primary_contact=PrimaryContact(name="x", email="x@y.test"),
            ),
            signed_contract_ref="x",
        ),
    )
    await session.commit()
    assert out.kyc_status == "NEEDS_REVIEW"
    assert out.kyb_status == "NEEDS_REVIEW"
