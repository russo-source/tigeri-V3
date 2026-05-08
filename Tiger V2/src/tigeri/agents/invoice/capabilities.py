"""Six capabilities for the Invoice Agent (TIGERI_AGENT_CATALOG_v1.md section 6.1.2)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.invoice.adapters.gl import GLAdapter, GLPostRequest, PostingResult
from tigeri.agents.invoice.adapters.inbox import InboxAdapter
from tigeri.agents.invoice.adapters.ocr import OCRAdapter
from tigeri.agents.invoice.approval import ApprovalDecision, ApprovalMatrix
from tigeri.agents.invoice.schemas import Invoice, InvoiceLineItem


@dataclass
class CapturedDocument:
    body: bytes
    media_type: str
    document_hash: str

    @property
    def text(self) -> str:
        """Convenience: body decoded as text. Only valid for text/* media types."""
        return self.body.decode("utf-8")


@dataclass
class ExtractedInvoice:
    vendor_name: str
    currency: str
    amount_total: Decimal
    tax_total: Decimal
    invoice_number: str
    po_reference: str | None
    line_items: list[InvoiceLineItem]
    raw: dict[str, Any]


@dataclass
class ValidationResult:
    status: str  # VALID | NEEDS_REVIEW | REJECTED
    reasons: list[str]


# Capability 1 ------------------------------------------------------------


async def capture(inbox: InboxAdapter, content_ref: str) -> CapturedDocument:
    body, media_type = await inbox.fetch_bytes(content_ref)
    digest = sha256(body).hexdigest()
    return CapturedDocument(body=body, media_type=media_type, document_hash=digest)


# Capability 2 ------------------------------------------------------------


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "na"}:
        return Decimal(default)
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return Decimal(default)


async def extract(ocr: OCRAdapter, document: CapturedDocument) -> ExtractedInvoice:
    raw = await ocr.extract_fields(document.body, document.media_type)
    return ExtractedInvoice(
        vendor_name=str(raw.get("vendor_name") or "UNKNOWN"),
        currency=str(raw.get("currency") or "USD").upper(),
        amount_total=_to_decimal(raw.get("amount_total")),
        tax_total=_to_decimal(raw.get("tax_total")),
        invoice_number=str(raw.get("invoice_number") or "UNKNOWN"),
        po_reference=raw.get("po_reference"),
        line_items=[
            InvoiceLineItem(
                description=str(li.get("description") or ""),
                qty=_to_decimal(li.get("qty"), default="1"),
                unit_price=_to_decimal(li.get("unit_price")),
            )
            for li in (raw.get("line_items") or [])
        ],
        raw=raw,
    )


# Capability 3 ------------------------------------------------------------


async def validate(
    session: AsyncSession,
    tenant_id: str,
    extracted: ExtractedInvoice,
    document_hash: str,
) -> ValidationResult:
    reasons: list[str] = []

    if len(extracted.currency) != 3 or not extracted.currency.isalpha():
        reasons.append(f"invalid currency: {extracted.currency}")
    if extracted.amount_total <= 0:
        reasons.append("amount_total must be > 0")
    if extracted.vendor_name in {"", "UNKNOWN"}:
        reasons.append("vendor_name missing")

    dup = await session.scalar(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.document_hash == document_hash,
        )
    )
    if dup is not None:
        reasons.append(f"duplicate of invoice {dup.id}")
        return ValidationResult(status="REJECTED", reasons=reasons)

    if reasons:
        return ValidationResult(status="NEEDS_REVIEW", reasons=reasons)
    return ValidationResult(status="VALID", reasons=[])


# Capability 4 ------------------------------------------------------------


def route(matrix: ApprovalMatrix, extracted: ExtractedInvoice) -> ApprovalDecision:
    return matrix.evaluate(extracted.amount_total)


# Capability 5 ------------------------------------------------------------


async def post(
    gl: GLAdapter,
    session: AsyncSession,
    tenant_id: str,
    invoice_id: str,
    extracted: ExtractedInvoice,
    decision: ApprovalDecision,
) -> PostingResult:
    if not decision.approved:
        return PostingResult(posting_reference="", posted=False)
    tax_label = str(extracted.raw.get("tax_rate_label") or "")
    req = GLPostRequest(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        amount=extracted.amount_total,
        currency=extracted.currency,
        vendor_name=extracted.vendor_name,
        invoice_number=extracted.invoice_number,
        line_description=f"Tigeri invoice {invoice_id} ({extracted.vendor_name})",
        tax_total=extracted.tax_total,
        tax_rate_label=tax_label,
    )
    return await gl.post(req, session)


# Capability 6 ------------------------------------------------------------


@dataclass
class EventReceipt:
    event_name: str
    invoice_id: str
    emitted_at: datetime


async def emit_event(invoice_id: str) -> EventReceipt:
    """Placeholder consumer-registry hook. Section 9 dependency map records
    Invoice Agent → Financial Reporting Agent and Invoice Agent → Compliance &
    Audit Agent, both fed by this event in later slices.
    """

    return EventReceipt(
        event_name="invoice_posted", invoice_id=invoice_id, emitted_at=datetime.now(UTC)
    )
