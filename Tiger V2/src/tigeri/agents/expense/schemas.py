from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class GeoLocation(BaseModel):
    lat: float
    lon: float


class ExpenseInput(BaseModel):
    """Section 6.2.3 input schema."""

    tenant_id: str
    submitter_id: str
    image_ref: str  # ``inline:<text>``, ``s3://bucket/key``, or ``file://...``
    captured_at: datetime
    geolocation: GeoLocation | None = None


class ExpenseOutput(BaseModel):
    """Section 6.2.4 output schema."""

    tenant_id: str
    expense_id: str
    merchant: str
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    category: str
    policy_status: Literal["WITHIN_POLICY", "OUT_OF_POLICY", "NEEDS_REVIEW"]
    reconciliation_status: Literal["MATCHED", "UNMATCHED", "PENDING"]
    matched_card_txn_id: str = ""


# ---- Persistence ----------------------------------------------------------


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    submitter_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    merchant: Mapped[str] = mapped_column(String(256), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_card_txn_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CardTransaction(Base):
    """Stub corporate card transaction feed table for reconciliation tests."""

    __tablename__ = "card_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    merchant: Mapped[str] = mapped_column(String(256), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched_expense_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
