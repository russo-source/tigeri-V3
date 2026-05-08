import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.audit.record import AuditRecord
from tigeri.core.ids import new_id


@dataclass
class AuditEvent:
    actor: str
    action: str
    target_resource: str
    tenant_id: str
    outcome: str
    trace_id: str
    payload: dict[str, Any] | None = None


async def emit(session: AsyncSession, event: AuditEvent) -> AuditRecord:
    record = AuditRecord(
        id=new_id("audit"),
        actor=event.actor,
        action=event.action,
        target_resource=event.target_resource,
        tenant_id=event.tenant_id,
        outcome=event.outcome,
        trace_id=event.trace_id,
        timestamp_utc=datetime.now(UTC),
        payload_json=json.dumps(event.payload) if event.payload is not None else None,
        chain_position=None,
        backfilled_at=None,
    )
    session.add(record)
    await session.flush()
    return record


def event_dict(event: AuditEvent) -> dict[str, Any]:
    return asdict(event)
