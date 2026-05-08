from datetime import UTC, datetime

import pytest

from tigeri.agents.invoice import capabilities as caps
from tigeri.agents.invoice.adapters.gl import StubGLAdapter
from tigeri.agents.invoice.adapters.inbox import LocalInboxAdapter
from tigeri.agents.invoice.adapters.ocr import HeuristicOCRAdapter
from tigeri.agents.invoice.approval import ApprovalMatrix
from tigeri.agents.invoice.schemas import Invoice


SAMPLE = (
    "vendor: Acme Pty Ltd\n"
    "currency: AUD\n"
    "total: 250.00\n"
    "tax: 25.00\n"
    "invoice: INV-001\n"
    "po: PO-9\n"
    "due: 2026-05-30\n"
)


@pytest.mark.asyncio
async def test_capture_and_extract_returns_structured_fields():
    captured = await caps.capture(LocalInboxAdapter(), f"inline:{SAMPLE}")
    extracted = await caps.extract(HeuristicOCRAdapter(), captured)
    assert extracted.vendor_name == "Acme Pty Ltd"
    assert extracted.currency == "AUD"
    assert str(extracted.amount_total) == "250.00"
    assert str(extracted.tax_total) == "25.00"
    assert extracted.invoice_number == "INV-001"
    assert extracted.po_reference == "PO-9"


@pytest.mark.asyncio
async def test_validate_detects_duplicate(session):
    captured = await caps.capture(LocalInboxAdapter(), f"inline:{SAMPLE}")
    extracted = await caps.extract(HeuristicOCRAdapter(), captured)

    # Seed a row with same hash
    session.add(
        Invoice(
            id="inv_seed",
            tenant_id="tnt_dupe",
            vendor_name="x",
            currency="AUD",
            amount_total=extracted.amount_total,
            tax_total=extracted.tax_total,
            line_items_json={},
            validation_status="VALID",
            approval_status="APPROVED",
            posting_status="POSTED",
            posting_reference="seed",
            document_hash=captured.document_hash,
            received_at=datetime.now(UTC),
        )
    )
    await session.flush()

    result = await caps.validate(session, "tnt_dupe", extracted, captured.document_hash)
    assert result.status == "REJECTED"
    assert any("duplicate" in r for r in result.reasons)


def test_route_picks_correct_approver_band():
    matrix = ApprovalMatrix()
    decision_low = caps.route(matrix, _ext(100))
    decision_mid = caps.route(matrix, _ext(2000))
    decision_high = caps.route(matrix, _ext(60000))
    assert decision_low.approver == "system:auto"
    assert decision_mid.approver == "role:manager"
    assert not decision_high.approved


@pytest.mark.asyncio
async def test_post_uses_gl_adapter_and_returns_reference(session):
    gl = StubGLAdapter()
    posting = await caps.post(gl, session, "tnt", "inv_1", _ext(100), _approved())
    assert posting.posted
    assert posting.posting_reference.startswith("gl_")
    assert len(gl.postings) == 1


@pytest.mark.asyncio
async def test_routing_adapter_surfaces_xero_failure_instead_of_falling_back(session):
    """Regression: when Xero is connected but the actual API call fails (e.g.
    'Organisation is not subscribed to currency INR'), the adapter used to
    silently fall through to the stub and the user got told 'Xero not
    connected'. It must now return posted=False with the human-readable
    error so the chat card shows what actually went wrong."""
    from unittest.mock import AsyncMock, patch
    from types import SimpleNamespace

    from tigeri.agents.invoice.adapters.gl import (
        GLPostRequest,
        RoutingGLAdapter,
    )
    from tigeri.integrations import token_manager

    fake_token_row = SimpleNamespace(meta_json={"mode": "real"})
    with (
        patch.object(token_manager, "get", new=AsyncMock(return_value=fake_token_row)),
        patch(
            "tigeri.agents.invoice.adapters.xero_gl.XeroGLAdapter.post",
            new=AsyncMock(
                side_effect=RuntimeError(
                    "Xero invoice POST 400: Organisation is not subscribed to currency INR"
                )
            ),
        ),
    ):
        adapter = RoutingGLAdapter()
        req = GLPostRequest(
            tenant_id="tnt_admin",
            invoice_id="inv_1",
            amount=_ext(100).amount_total,
            currency="INR",
            vendor_name="abc.ltd",
            invoice_number="INV-1",
        )
        result = await adapter.post(req, session)

    assert result.posted is False
    assert result.provider == "xero"
    assert "INR" in result.error
    # Don't have the user re-read Xero error verbatim — we add a hint.
    assert "Currencies" in result.error or "supports" in result.error.lower()


# Helpers ----


def _ext(amount: float):
    from decimal import Decimal

    return caps.ExtractedInvoice(
        vendor_name="V",
        currency="USD",
        amount_total=Decimal(str(amount)),
        tax_total=Decimal("0"),
        invoice_number="x",
        po_reference=None,
        line_items=[],
        raw={},
    )


def _approved():
    from tigeri.agents.invoice.approval import ApprovalDecision

    return ApprovalDecision(decided=True, approved=True, approver="system:auto", reason="ok")
