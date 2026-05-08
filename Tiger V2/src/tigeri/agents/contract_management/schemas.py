from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


LifecycleState = Literal["DRAFT", "ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED"]


class ContractInput(BaseModel):
    """Section 6.7.3 input schema."""

    tenant_id: str
    document_ref: str  # ``inline:`` / ``file://`` / ``s3://`` / ``data:``
    counterparty_hint: str = ""
    uploader_id: str


class KeyTerm(BaseModel):
    term: str
    value: str


class ContractOutput(BaseModel):
    """Section 6.7.4 output schema."""

    tenant_id: str
    contract_id: str
    counterparty: str
    effective_date: datetime
    expiry_date: datetime
    auto_renewal: bool
    key_terms: list[KeyTerm]
    lifecycle_state: LifecycleState


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    counterparty: Mapped[str] = mapped_column(String(256), nullable=False)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    auto_renewal: Mapped[bool] = mapped_column(default=False)
    contract_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    key_terms_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uploader_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
