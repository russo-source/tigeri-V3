from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext, BaseAgent
from tigeri.agents.invoice import capabilities as caps
from tigeri.agents.invoice.adapters.gl import GLAdapter, default_gl_adapter
from tigeri.agents.invoice.adapters.inbox import InboxAdapter, LocalInboxAdapter
from tigeri.agents.invoice.adapters.ocr import OCRAdapter, default_ocr_adapter
from tigeri.agents.invoice.approval import ApprovalMatrix
from tigeri.agents.invoice.schemas import Invoice, InvoiceInput, InvoiceOutput
from tigeri.core.ids import new_id


class InvoiceAgent(BaseAgent):
    agent_id = "invoice_agent"

    def __init__(
        self,
        inbox: InboxAdapter | None = None,
        ocr: OCRAdapter | None = None,
        gl: GLAdapter | None = None,
        matrix: ApprovalMatrix | None = None,
    ) -> None:
        super().__init__()
        self.inbox = inbox or LocalInboxAdapter()
        self.ocr = ocr or default_ocr_adapter()
        self.gl = gl or default_gl_adapter()
        self.matrix = matrix or ApprovalMatrix()

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: InvoiceInput,
    ) -> InvoiceOutput:
        invoice_id = new_id("inv")

        # Capability 1: capture
        captured = await caps.capture(self.inbox, request.document.content_ref)
        await self.audit(
            session, ctx, "capture", invoice_id, "OK", {"hash": captured.document_hash}
        )

        # Capability 2: extract
        extracted = await caps.extract(self.ocr, captured)
        await self.audit(
            session,
            ctx,
            "extract",
            invoice_id,
            "OK",
            {"vendor": extracted.vendor_name, "amount_total": str(extracted.amount_total)},
        )

        # Capability 3: validate
        validation = await caps.validate(session, ctx.tenant_id, extracted, captured.document_hash)
        await self.audit(
            session,
            ctx,
            "validate",
            invoice_id,
            validation.status,
            {"reasons": validation.reasons},
        )
        if validation.status == "REJECTED":
            return self._persist(
                session,
                ctx,
                invoice_id,
                request,
                extracted,
                captured.document_hash,
                validation_status="REJECTED",
                approval_status="DENIED",
                posting_status="NOT_POSTED",
                posting_reference="",
                posting_url="",
                posting_provider="",
            )

        # Capability 4: route
        decision = caps.route(self.matrix, extracted)
        await self.audit(
            session,
            ctx,
            "route",
            invoice_id,
            "APPROVED" if decision.approved else "PENDING",
            {"approver": decision.approver, "reason": decision.reason},
        )
        approval_status = "APPROVED" if decision.approved else "PENDING"

        # Capability 5: post
        posting = await caps.post(self.gl, session, ctx.tenant_id, invoice_id, extracted, decision)
        posting_status = "POSTED" if posting.posted else "NOT_POSTED"
        await self.audit(
            session,
            ctx,
            "post",
            invoice_id,
            posting_status,
            {"posting_reference": posting.posting_reference},
        )

        # Capability 6: emit_event
        event = await caps.emit_event(invoice_id)
        await self.audit(
            session,
            ctx,
            "emit_event",
            invoice_id,
            "OK",
            {"event_name": event.event_name, "emitted_at": event.emitted_at.isoformat()},
        )

        return self._persist(
            session,
            ctx,
            invoice_id,
            request,
            extracted,
            captured.document_hash,
            validation_status=validation.status,
            approval_status=approval_status,
            posting_status=posting_status,
            posting_reference=posting.posting_reference,
            posting_url=posting.view_url,
            posting_provider=posting.provider,
            posting_error=posting.error,
        )

    def _persist(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        invoice_id: str,
        request: InvoiceInput,
        extracted: caps.ExtractedInvoice,
        document_hash: str,
        *,
        validation_status: str,
        approval_status: str,
        posting_status: str,
        posting_reference: str,
        posting_url: str = "",
        posting_provider: str = "",
        posting_error: str = "",
    ) -> InvoiceOutput:
        row = Invoice(
            id=invoice_id,
            tenant_id=ctx.tenant_id,
            vendor_name=extracted.vendor_name,
            currency=extracted.currency,
            amount_total=extracted.amount_total,
            tax_total=extracted.tax_total,
            invoice_number=extracted.invoice_number,
            po_reference=extracted.po_reference,
            line_items_json={
                "items": [li.model_dump(mode="json") for li in extracted.line_items]
            },
            validation_status=validation_status,
            approval_status=approval_status,
            posting_status=posting_status,
            posting_reference=posting_reference,
            document_hash=document_hash,
            received_at=request.received_at.astimezone(UTC)
            if request.received_at.tzinfo
            else request.received_at.replace(tzinfo=UTC),
        )
        session.add(row)
        return InvoiceOutput(
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            vendor_name=extracted.vendor_name,
            currency=extracted.currency,
            amount_total=extracted.amount_total,
            tax_total=extracted.tax_total,
            line_items=extracted.line_items,
            validation_status=validation_status,  # type: ignore[arg-type]
            approval_status=approval_status,  # type: ignore[arg-type]
            posting_status=posting_status,  # type: ignore[arg-type]
            posting_reference=posting_reference,
            posting_url=posting_url,
            posting_provider=posting_provider,
            posting_error=posting_error,
        )


# Avoid unused-import warning in __init__-less wiring
_ = datetime
