"""LangGraph implementation of the Invoice Agent.

This is the canonical pattern for every agent going forward — each capability
becomes a graph node, state flows through a TypedDict, and the per-user
``session`` slice is checkpointed by a LangGraph saver so user behaviour
persists across calls.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from langgraph.graph import StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext
from tigeri.agents.invoice import capabilities as caps
from tigeri.agents.invoice.adapters.gl import GLAdapter, default_gl_adapter
from tigeri.agents.invoice.adapters.inbox import LocalInboxAdapter
from tigeri.agents.invoice.adapters.ocr import OCRAdapter, default_ocr_adapter
from tigeri.agents.invoice.approval import ApprovalMatrix
from tigeri.agents.invoice.schemas import Invoice, InvoiceInput, InvoiceOutput
from tigeri.core.ids import new_id
from tigeri.graph.base import BaseGraphAgent, current_db_session
from tigeri.graph.state import BaseAgentState


class InvoiceGraphState(BaseAgentState, total=False):
    request: InvoiceInput
    invoice_id: str
    captured: caps.CapturedDocument
    extracted: caps.ExtractedInvoice
    validation: caps.ValidationResult
    decision: Any
    posting: Any
    output: InvoiceOutput


class InvoiceGraphAgent(BaseGraphAgent):
    agent_id = "invoice_agent"
    state_schema = InvoiceGraphState

    def __init__(
        self,
        inbox: LocalInboxAdapter | None = None,
        ocr: OCRAdapter | None = None,
        gl: GLAdapter | None = None,
        matrix: ApprovalMatrix | None = None,
        checkpointer=None,
    ) -> None:
        self.inbox = inbox or LocalInboxAdapter()
        self.ocr = ocr or default_ocr_adapter()
        self.gl = gl or default_gl_adapter()
        self.matrix = matrix or ApprovalMatrix()
        super().__init__(checkpointer=checkpointer)

    # ---- Public entrypoint ------------------------------------------------

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: InvoiceInput,
        *,
        session_id: str = "default",
        user_id: str = "anonymous",
    ) -> InvoiceOutput:
        invoice_id = new_id("inv")
        final = await self.run_graph(
            ctx=ctx,
            session_id=session_id,
            user_id=user_id,
            db_session=session,
            initial={
                "request": request,
                "invoice_id": invoice_id,
            },
        )
        return final["output"]

    # ---- Graph definition -------------------------------------------------

    def build_graph(self) -> StateGraph:
        g: StateGraph = StateGraph(InvoiceGraphState)
        g.add_node("capture", self._node_capture)
        g.add_node("extract", self._node_extract)
        g.add_node("validate", self._node_validate)
        g.add_node("route", self._node_route)
        g.add_node("post", self._node_post)
        g.add_node("emit_event", self._node_emit_event)

        g.set_entry_point("capture")
        g.add_edge("capture", "extract")
        g.add_edge("extract", "validate")
        g.add_conditional_edges(
            "validate",
            self._after_validate,
            {"continue": "route", "stop": "emit_event"},
        )
        g.add_edge("route", "post")
        g.add_edge("post", "emit_event")
        g.add_edge("emit_event", self.end())
        return g

    # ---- Nodes ------------------------------------------------------------

    async def _node_capture(self, state: InvoiceGraphState) -> dict:
        request: InvoiceInput = state["request"]
        captured = await caps.capture(self.inbox, request.document.content_ref)
        await self._audit(
            state, "capture", state["invoice_id"], "OK", {"hash": captured.document_hash}
        )
        return {"captured": captured}

    async def _node_extract(self, state: InvoiceGraphState) -> dict:
        extracted = await caps.extract(self.ocr, state["captured"])
        await self._audit(
            state,
            "extract",
            state["invoice_id"],
            "OK",
            {"vendor": extracted.vendor_name, "amount_total": str(extracted.amount_total)},
        )
        return {"extracted": extracted}

    async def _node_validate(self, state: InvoiceGraphState) -> dict:
        result = await caps.validate(
            current_db_session(),
            state["session"]["tenant_id"],
            state["extracted"],
            state["captured"].document_hash,
        )
        await self._audit(
            state, "validate", state["invoice_id"], result.status, {"reasons": result.reasons}
        )
        # Update behaviour memory: track rejection streak per user
        session = dict(state["session"])
        behaviour = dict(session.get("behaviour", {}))
        if result.status == "REJECTED":
            behaviour["rejection_streak"] = behaviour.get("rejection_streak", 0) + 1
        else:
            behaviour["rejection_streak"] = 0
        behaviour["last_validation"] = result.status
        session["behaviour"] = behaviour
        return {"validation": result, "session": session}

    @staticmethod
    def _after_validate(state: InvoiceGraphState) -> str:
        return "stop" if state["validation"].status == "REJECTED" else "continue"

    async def _node_route(self, state: InvoiceGraphState) -> dict:
        decision = caps.route(self.matrix, state["extracted"])
        await self._audit(
            state,
            "route",
            state["invoice_id"],
            "APPROVED" if decision.approved else "PENDING",
            {"approver": decision.approver, "reason": decision.reason},
        )
        return {"decision": decision}

    async def _node_post(self, state: InvoiceGraphState) -> dict:
        posting = await caps.post(
            self.gl,
            current_db_session(),
            state["session"]["tenant_id"],
            state["invoice_id"],
            state["extracted"],
            state["decision"],
        )
        outcome = "POSTED" if posting.posted else "NOT_POSTED"
        await self._audit(
            state, "post", state["invoice_id"], outcome, {"posting_reference": posting.posting_reference}
        )
        return {"posting": posting}

    async def _node_emit_event(self, state: InvoiceGraphState) -> dict:
        event = await caps.emit_event(state["invoice_id"])
        await self._audit(
            state,
            "emit_event",
            state["invoice_id"],
            "OK",
            {"event_name": event.event_name, "emitted_at": event.emitted_at.isoformat()},
        )

        validation = state["validation"]
        decision = state.get("decision")
        posting = state.get("posting")

        approval_status = (
            "APPROVED"
            if decision and decision.approved
            else "DENIED"
            if validation.status == "REJECTED"
            else "PENDING"
        )
        posting_status = "POSTED" if posting and posting.posted else "NOT_POSTED"
        posting_reference = posting.posting_reference if posting else ""
        posting_url = posting.view_url if posting else ""
        posting_provider = posting.provider if posting else ""
        posting_error = posting.error if posting else ""

        request: InvoiceInput = state["request"]
        extracted = state["extracted"]
        invoice_id = state["invoice_id"]
        db_session: AsyncSession = current_db_session()

        row = Invoice(
            id=invoice_id,
            tenant_id=state["session"]["tenant_id"],
            vendor_name=extracted.vendor_name,
            currency=extracted.currency,
            amount_total=extracted.amount_total,
            tax_total=extracted.tax_total,
            invoice_number=extracted.invoice_number,
            po_reference=extracted.po_reference,
            line_items_json={
                "items": [li.model_dump(mode="json") for li in extracted.line_items]
            },
            validation_status=validation.status,
            approval_status=approval_status,
            posting_status=posting_status,
            posting_reference=posting_reference,
            document_hash=state["captured"].document_hash,
            received_at=request.received_at.astimezone(UTC)
            if request.received_at.tzinfo
            else request.received_at.replace(tzinfo=UTC),
        )
        db_session.add(row)

        output = InvoiceOutput(
            tenant_id=state["session"]["tenant_id"],
            invoice_id=invoice_id,
            vendor_name=extracted.vendor_name,
            currency=extracted.currency,
            amount_total=extracted.amount_total,
            tax_total=extracted.tax_total,
            line_items=extracted.line_items,
            validation_status=validation.status,  # type: ignore[arg-type]
            approval_status=approval_status,  # type: ignore[arg-type]
            posting_status=posting_status,  # type: ignore[arg-type]
            posting_reference=posting_reference,
            posting_url=posting_url,
            posting_provider=posting_provider,
            posting_error=posting_error,
        )
        return {"output": output}

    # ---- Audit hook -------------------------------------------------------

    async def _audit(
        self,
        state: InvoiceGraphState,
        action: str,
        target: str,
        outcome: str,
        payload: dict | None,
    ) -> None:
        ctx = AgentRunContext(
            tenant_id=state["session"]["tenant_id"],
            actor=f"user:{state['session']['user_id']}",
            trace_id=state["trace_id"],
        )
        await self.audit(current_db_session(), ctx, action, target, outcome, payload)
