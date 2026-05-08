"""GL adapter that posts invoices into Xero via the integration layer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.invoice.adapters.gl import GLPostRequest, PostingResult
from tigeri.integrations.xero import XeroClient, XeroInvoiceRequest


class XeroGLAdapter:
    async def post(self, req: GLPostRequest, session: AsyncSession) -> PostingResult:
        client = await XeroClient.for_tenant(session, req.tenant_id)
        result = await client.post_invoice(
            XeroInvoiceRequest(
                contact_name=req.vendor_name or "Tigeri Vendor",
                line_description=req.line_description or f"Tigeri invoice {req.invoice_id}",
                amount=req.amount,
                currency=req.currency or "USD",
                invoice_number=req.invoice_number or req.invoice_id,
                due_date=req.due_date,
                tax_total=req.tax_total,
                tax_rate_label=req.tax_rate_label,
            )
        )
        return PostingResult(
            posting_reference=f"xero:{result.xero_invoice_id}",
            posted=True,
            view_url=result.view_url,
            provider="xero",
        )
