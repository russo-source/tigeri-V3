from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class AdminSubject(BaseModel):
    type: Literal["EMPLOYEE", "CONTRACTOR", "CLIENT"]
    id: str


class AdminInput(BaseModel):
    """Section 6.3.3 input schema."""

    tenant_id: str
    workflow_template_id: str
    subject: AdminSubject
    initiator_id: str
    context: dict[str, Any] = {}


class CommunicationReceipt(BaseModel):
    channel: Literal["EMAIL", "SMS", "IN_APP"]
    recipient_id: str
    delivered_at: datetime


class AdminOutput(BaseModel):
    """Section 6.3.4 output schema."""

    tenant_id: str
    workflow_instance_id: str
    current_step: str
    status: Literal["IN_PROGRESS", "COMPLETED", "BLOCKED", "CANCELLED"]
    documents_generated: list[str]
    communications_sent: list[CommunicationReceipt]


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workflow_template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    documents: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    communications: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
