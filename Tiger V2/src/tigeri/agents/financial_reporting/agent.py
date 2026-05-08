"""Financial Reporting Agent — Priority 6, Phase 1, OBSERVER tier.

Reads posted invoices and posted expenses from the tenant's Postgres slice
(those are what `Invoice Agent` and `Expense Agent` write today) and rolls
them up into a P&L, cashflow summary, and KPI list. In production the source
of truth is the tenant's general ledger (catalog requires
``general ledger / accounting system`` integration); the slice 1 stub
substitutes Tigeri's own posted-invoice / submitted-expense rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from langgraph.graph import StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext
from tigeri.agents.expense.schemas import Expense
from tigeri.agents.financial_reporting.schemas import (
    FinancialReport,
    FRInput,
    FROutput,
    KPI,
    Period,
)
from tigeri.agents.invoice.schemas import Invoice
from tigeri.core.ids import new_id
from tigeri.graph.base import BaseGraphAgent, current_db_session
from tigeri.graph.state import BaseAgentState


class FRGraphState(BaseAgentState, total=False):
    request: FRInput
    report_id: str
    revenue_total: Decimal
    expense_total: Decimal
    cash_in: Decimal
    cash_out: Decimal
    kpis: list[KPI]
    rendered_ref: str
    output: FROutput


class FinancialReportingAgent(BaseGraphAgent):
    agent_id = "financial_reporting_agent"
    state_schema = FRGraphState

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: FRInput,
        *,
        session_id: str = "default",
        user_id: str = "anonymous",
    ) -> FROutput:
        report_id = new_id("rpt")
        final = await self.run_graph(
            ctx=ctx,
            session_id=session_id,
            user_id=user_id,
            db_session=session,
            initial={"request": request, "report_id": report_id},
        )
        return final["output"]

    def build_graph(self) -> StateGraph:
        g: StateGraph = StateGraph(FRGraphState)
        g.add_node("pull_balances", self._node_pull_balances)
        g.add_node("compute_pnl", self._node_compute_pnl)
        g.add_node("compute_cashflow", self._node_compute_cashflow)
        g.add_node("compute_kpis", self._node_compute_kpis)
        g.add_node("render", self._node_render)
        g.add_node("deliver", self._node_deliver)
        g.set_entry_point("pull_balances")
        g.add_edge("pull_balances", "compute_pnl")
        g.add_edge("compute_pnl", "compute_cashflow")
        g.add_edge("compute_cashflow", "compute_kpis")
        g.add_edge("compute_kpis", "render")
        g.add_edge("render", "deliver")
        g.add_edge("deliver", self.end())
        return g

    async def _node_pull_balances(self, state: FRGraphState) -> dict:
        request = state["request"]
        db = current_db_session()
        period_start = self._utc(request.period.start)
        period_end = self._utc(request.period.end)
        tenant_id = state["session"]["tenant_id"]

        revenue_rows = await db.scalars(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.posting_status == "POSTED",
                Invoice.received_at >= period_start,
                Invoice.received_at <= period_end,
            )
        )
        revenue_total = sum((r.amount_total for r in revenue_rows), Decimal("0"))

        expense_rows = await db.scalars(
            select(Expense).where(
                Expense.tenant_id == tenant_id,
                Expense.captured_at >= period_start,
                Expense.captured_at <= period_end,
            )
        )
        expense_total = sum((r.amount for r in expense_rows), Decimal("0"))

        await self._audit(
            state,
            "pull_balances",
            state["report_id"],
            "OK",
            {
                "revenue_total": str(revenue_total),
                "expense_total": str(expense_total),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        return {
            "revenue_total": revenue_total,
            "expense_total": expense_total,
        }

    async def _node_compute_pnl(self, state: FRGraphState) -> dict:
        net = (state.get("revenue_total") or Decimal("0")) - (
            state.get("expense_total") or Decimal("0")
        )
        await self._audit(
            state, "compute_pnl", state["report_id"], "OK", {"net_income": str(net)}
        )
        return {"net_income": net}

    async def _node_compute_cashflow(self, state: FRGraphState) -> dict:
        # Slice 1 surrogate: cash_in == revenue_total (posted invoices),
        # cash_out == expense_total. Real cashflow needs treasury/banking feed.
        cash_in = state.get("revenue_total") or Decimal("0")
        cash_out = state.get("expense_total") or Decimal("0")
        await self._audit(
            state,
            "compute_cashflow",
            state["report_id"],
            "OK",
            {"cash_in": str(cash_in), "cash_out": str(cash_out)},
        )
        return {"cash_in": cash_in, "cash_out": cash_out}

    async def _node_compute_kpis(self, state: FRGraphState) -> dict:
        revenue = state.get("revenue_total") or Decimal("0")
        expense = state.get("expense_total") or Decimal("0")
        net = revenue - expense
        margin = (net / revenue * Decimal("100")) if revenue > 0 else Decimal("0")
        kpis: list[KPI] = [
            KPI(name="revenue_total", value=revenue, unit="currency"),
            KPI(name="expense_total", value=expense, unit="currency"),
            KPI(name="net_income", value=net, unit="currency"),
            KPI(name="net_margin_pct", value=margin.quantize(Decimal("0.01")), unit="percent"),
        ]
        await self._audit(
            state, "compute_kpis", state["report_id"], "OK", {"kpi_count": len(kpis)}
        )
        return {"kpis": kpis}

    async def _node_render(self, state: FRGraphState) -> dict:
        # Slice 1: rendered_artifact_ref points to a synthetic in-DB record.
        # Production would PUT a PDF/HTML to S3 and return the s3:// URL.
        ref = f"db://financial_reports/{state['report_id']}"
        await self._audit(
            state, "render", state["report_id"], "OK", {"artifact": ref}
        )
        return {"rendered_ref": ref}

    async def _node_deliver(self, state: FRGraphState) -> dict:
        request = state["request"]
        db = current_db_session()
        period_start = self._utc(request.period.start)
        period_end = self._utc(request.period.end)
        revenue = state.get("revenue_total") or Decimal("0")
        expense = state.get("expense_total") or Decimal("0")
        net = revenue - expense
        kpis: list[KPI] = state.get("kpis") or []
        report_id = state["report_id"]
        rendered_ref = state.get("rendered_ref") or ""
        generated_at = datetime.now(UTC)

        row = FinancialReport(
            id=report_id,
            tenant_id=state["session"]["tenant_id"],
            report_type=request.report_type,
            period_start=period_start,
            period_end=period_end,
            revenue_total=revenue,
            expense_total=expense,
            net_income=net,
            cash_in=state.get("cash_in") or Decimal("0"),
            cash_out=state.get("cash_out") or Decimal("0"),
            kpis_json={"items": [k.model_dump(mode="json") for k in kpis]},
            rendered_artifact_ref=rendered_ref,
            generated_at=generated_at,
        )
        db.add(row)
        await self._audit(
            state, "deliver", report_id, "OK", {"to": "tenant_dashboard"}
        )
        output = FROutput(
            tenant_id=state["session"]["tenant_id"],
            report_id=report_id,
            report_type=request.report_type,
            period=Period(start=period_start, end=period_end),
            rendered_artifact_ref=rendered_ref,
            kpis=kpis,
            generated_at=generated_at,
        )
        return {"output": output}

    @staticmethod
    def _utc(dt: datetime) -> datetime:
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    async def _audit(
        self,
        state: FRGraphState,
        action: str,
        target: str,
        outcome: str,
        payload: dict[str, Any] | None,
    ) -> None:
        ctx = AgentRunContext(
            tenant_id=state["session"]["tenant_id"],
            actor=f"user:{state['session']['user_id']}",
            trace_id=state["trace_id"],
        )
        await self.audit(current_db_session(), ctx, action, target, outcome, payload)
