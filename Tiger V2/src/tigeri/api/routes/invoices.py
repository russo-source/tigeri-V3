from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.invoice.schemas import Invoice
from tigeri.api.deps import get_session
from tigeri.auth.scope import TenantScope, get_scope

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == scope.tenant_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
    return {
        "tenant_id": row.tenant_id,
        "invoice_id": row.id,
        "vendor_name": row.vendor_name,
        "currency": row.currency,
        "amount_total": str(row.amount_total),
        "tax_total": str(row.tax_total),
        "validation_status": row.validation_status,
        "approval_status": row.approval_status,
        "posting_status": row.posting_status,
        "posting_reference": row.posting_reference,
    }
