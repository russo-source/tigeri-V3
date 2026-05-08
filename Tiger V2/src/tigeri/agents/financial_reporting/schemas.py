from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


ReportType = Literal["PNL", "CASHFLOW", "KPI_DASHBOARD"]
Comparative = Literal["PRIOR_PERIOD", "PRIOR_YEAR", "BUDGET"]


class Period(BaseModel):
    start: datetime
    end: datetime


class FRInput(BaseModel):
    """Section 6.6.3 input schema."""

    tenant_id: str
    report_type: ReportType
    period: Period
    comparatives: list[Comparative] = []


class KPI(BaseModel):
    name: str
    value: Decimal
    unit: str


class FROutput(BaseModel):
    """Section 6.6.4 output schema."""

    tenant_id: str
    report_id: str
    report_type: ReportType
    period: Period
    rendered_artifact_ref: str
    kpis: list[KPI]
    generated_at: datetime


class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revenue_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    expense_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    cash_in: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    cash_out: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kpis_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rendered_artifact_ref: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
