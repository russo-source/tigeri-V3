"""Hash-chain writer with Postgres advisory-lock serialisation per tenant.

Substitutes for the spec's Redis lock. The advisory lock is held for the
duration of the SELECT(prev_hash) + INSERT transaction — same guarantees,
zero new infrastructure required.

HMAC key comes from settings.secret_encryption_key. If/when we rotate it,
existing rows can no longer be re-verified with the new key — keep the old
key for verification (out of scope here; record the key version with each
row in a future migration if rotation is needed).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.audit_chain.models import AuditLog
from tigeri.core.config import get_settings
from tigeri.core.ids import new_id

GENESIS = "genesis"


class AuditChainBroken(RuntimeError):
    """Raised by verify_chain when a row's recomputed hash doesn't match."""


@dataclass(slots=True)
class AuditEntry:
    """Input to AuditChainWriter.write — narrow surface for callers."""

    tenant_id: str
    event_type: str  # capability_invoked, action_confirmed, connector_connected, etc.
    result: str  # success | failure | partial | declined_permission | declined_policy | expired | cancelled
    user_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    capability: str | None = None
    parameters_redacted: dict[str, Any] | None = None
    parameters_ref: str | None = None
    diff_before_ref: str | None = None
    diff_after_ref: str | None = None
    xero_request_id: str | None = None
    idempotency_key: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    channel: str | None = None
    error_detail: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _hmac_key() -> bytes:
    settings = get_settings()
    if not settings.secret_encryption_key:
        raise RuntimeError(
            "TIGERI_SECRET_ENCRYPTION_KEY is required for the audit chain"
        )
    return settings.secret_encryption_key.encode("utf-8")


def _compute_signature(
    *,
    row_id: str,
    tenant_id: str,
    event_type: str,
    result: str,
    created_at: datetime,
    prev_hash: str,
) -> str:
    payload = "|".join(
        [
            row_id,
            tenant_id,
            event_type,
            result,
            created_at.astimezone(UTC).isoformat(),
            prev_hash,
        ]
    )
    return hmac.new(_hmac_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class AuditChainWriter:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def write(self, entry: AuditEntry) -> AuditLog:
        # Acquire transaction-scoped advisory lock keyed on tenant_id. Two
        # concurrent inserts for the same tenant serialise here; for different
        # tenants they don't block each other.
        await self.db.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(:tid, 0))"
            ).bindparams(tid=entry.tenant_id)
        )

        prev_hash = await self._latest_signed_hash(entry.tenant_id)
        row_id = new_id("aud")
        created_at = datetime.now(UTC)

        signed_hash = _compute_signature(
            row_id=row_id,
            tenant_id=entry.tenant_id,
            event_type=entry.event_type,
            result=entry.result,
            created_at=created_at,
            prev_hash=prev_hash,
        )

        row = AuditLog(
            id=row_id,
            tenant_id=entry.tenant_id,
            user_id=entry.user_id,
            conversation_id=entry.conversation_id,
            session_id=entry.session_id,
            event_type=entry.event_type,
            capability=entry.capability,
            result=entry.result,
            parameters_redacted=entry.parameters_redacted,
            parameters_ref=entry.parameters_ref,
            diff_before_ref=entry.diff_before_ref,
            diff_after_ref=entry.diff_after_ref,
            xero_request_id=entry.xero_request_id,
            idempotency_key=entry.idempotency_key,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
            channel=entry.channel,
            error_detail=entry.error_detail,
            signed_hash=signed_hash,
            prev_hash=prev_hash,
            created_at=created_at,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def _latest_signed_hash(self, tenant_id: str) -> str:
        res = await self.db.execute(
            select(AuditLog.signed_hash)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        prev = res.scalar_one_or_none()
        return prev or GENESIS


async def verify_chain(db: AsyncSession, tenant_id: str) -> tuple[bool, int, str | None]:
    """Recompute every row's hash in order. Returns
    ``(ok, rows_checked, broken_row_id)``. broken_row_id is set when ok is False.
    """
    res = await db.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    expected_prev = GENESIS
    count = 0
    for row in res.scalars():
        recomputed = _compute_signature(
            row_id=row.id,
            tenant_id=row.tenant_id,
            event_type=row.event_type,
            result=row.result,
            created_at=row.created_at,
            prev_hash=expected_prev,
        )
        if recomputed != row.signed_hash or row.prev_hash != expected_prev:
            return False, count, row.id
        expected_prev = row.signed_hash
        count += 1
    return True, count, None
