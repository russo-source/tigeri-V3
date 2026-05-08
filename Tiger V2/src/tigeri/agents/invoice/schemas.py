from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class InvoiceLineItem(BaseModel):
    description: str
    qty: Decimal
    unit_price: Decimal


# ---- API I/O (section 6.1.3 / 6.1.4) -------------------------------------


class InvoiceDocument(BaseModel):
    media_type: str
    content_ref: str  # URI or local path; for slice 1 may also contain inline text via "inline:..."


class InvoiceInput(BaseModel):
    """Section 6.1.3 input schema."""

    tenant_id: str
    source: Literal["EMAIL", "UPLOAD", "API"]
    document: InvoiceDocument
    received_at: datetime


class InvoiceOutput(BaseModel):
    """Section 6.1.4 output schema."""

    tenant_id: str
    invoice_id: str
    vendor_name: str
    currency: str = Field(min_length=3, max_length=3)
    amount_total: Decimal
    tax_total: Decimal
    line_items: list[InvoiceLineItem]
    validation_status: Literal["VALID", "NEEDS_REVIEW", "REJECTED"]
    approval_status: Literal["PENDING", "APPROVED", "DENIED"]
    posting_status: Literal["POSTED", "NOT_POSTED"]
    posting_reference: str = ""
    posting_url: str = ""  # Provider deep link (e.g. Xero invoice page)
    posting_provider: str = ""  # "xero" | "qb_sandbox" | "stub"
    # Populated when the upstream provider (Xero/QB) actively rejected the
    # invoice — e.g. "Organisation is not subscribed to currency INR". The
    # chat card surfaces this verbatim so the user knows what to fix.
    posting_error: str = ""


# ---- Persistence ---------------------------------------------------------


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vendor_name: Mapped[str] = mapped_column(String(256), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    po_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    line_items_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    posting_status: Mapped[str] = mapped_column(String(32), nullable=False)
    posting_reference: Mapped[str] = mapped_column(String(128), default="")
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
