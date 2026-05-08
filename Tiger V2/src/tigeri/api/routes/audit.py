from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.api.deps import get_session
from tigeri.audit.record import AuditRecord
from tigeri.auth.scope import TenantScope, get_scope

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/records")
async def list_records(
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
    trace_id: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[dict]:
    stmt = select(AuditRecord).where(AuditRecord.tenant_id == scope.tenant_id)
    if trace_id:
        stmt = stmt.where(AuditRecord.trace_id == trace_id)
    if actor:
        stmt = stmt.where(AuditRecord.actor == actor)
    stmt = stmt.order_by(AuditRecord.timestamp_utc.desc()).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "target_resource": r.target_resource,
            "tenant_id": r.tenant_id,
            "outcome": r.outcome,
            "trace_id": r.trace_id,
            "timestamp_utc": r.timestamp_utc.isoformat(),
            "chain_position": r.chain_position,
            "backfilled_at": r.backfilled_at.isoformat() if r.backfilled_at else None,
        }
        for r in rows
    ]
