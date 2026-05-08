from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


KYCStatus = Literal["PASS", "FAIL", "NEEDS_REVIEW"]
KYBStatus = Literal["PASS", "FAIL", "NEEDS_REVIEW"]


class PrimaryContact(BaseModel):
    name: str
    email: str


class ClientRecord(BaseModel):
    legal_name: str
    registration_id: str
    primary_contact: PrimaryContact


class COInput(BaseModel):
    """Section 6.8.3 input schema."""

    tenant_id: str
    client_record: ClientRecord
    signed_contract_ref: str


class COOutput(BaseModel):
    """Section 6.8.4 output schema."""

    tenant_id: str
    onboarding_id: str
    kyc_status: KYCStatus
    kyb_status: KYBStatus
    project_plan_ref: str
    kickoff_meeting_id: str
    completed_at: datetime


class Onboarding(Base):
    __tablename__ = "onboardings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_legal_name: Mapped[str] = mapped_column(String(256), nullable=False)
    registration_id: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_contact_name: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_contact_email: Mapped[str] = mapped_column(String(256), nullable=False)
    signed_contract_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    kyc_status: Mapped[str] = mapped_column(String(32), nullable=False)
    kyb_status: Mapped[str] = mapped_column(String(32), nullable=False)
    project_plan_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    kickoff_meeting_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
