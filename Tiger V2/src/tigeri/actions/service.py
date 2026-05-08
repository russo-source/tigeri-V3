"""Pending-action service: propose, confirm, cancel, sweep.

The capability registry is intentionally lightweight here — Phase 3 lays the
infrastructure. Wiring specific Finance Agent capabilities (xero.mark_invoice_paid
etc.) through this gate is a follow-up.

Encryption: parameters are encrypted with Fernet via the existing
`tigeri.integrations.encryption` helpers — the same key used for OAuth tokens.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.actions.models import PendingAction
from tigeri.core.ids import new_id
from tigeri.integrations.encryption import decrypt, encrypt

PENDING_LIFETIME = timedelta(minutes=5)


class PendingActionInvalid(Exception):
    """Raised when a confirmation_token doesn't match a pending row owned by
    the current scope, or when status/tenant guards fail."""


class PendingActionExpired(Exception):
    """Raised when a pending row's expires_at is in the past."""


def _idempotency_key(capability: str, parameters: dict[str, Any]) -> str:
    """Per-propose unique key.

    Was originally a content-hash (sha256 of capability+params), which meant
    two separate user proposes with identical text collided on the same key
    and the partial unique index ``WHERE status='executed'`` rejected the
    second `mark_executed`. The side effect (Xero post / GL post) had
    already run by then, leaving the system in an inconsistent state.

    Now we use a fresh random token per propose. The defense-against-double-
    confirm-of-the-same-action is provided by `confirm()`'s SELECT FOR UPDATE
    on confirmation_token (transitions pending → confirmed atomically; the
    second click sees status='confirmed' and raises PendingActionInvalid).
    The capability+params digest is appended for traceability only.
    """
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(
        json.dumps(
            {"capability": capability, "params": parameters},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"{nonce}:{digest}"


class PendingActionService:
    """Stateless helper. Holds a reference to the AsyncSession of the request."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def propose(
        self,
        *,
        tenant_id: str,
        user_id: str,
        capability: str,
        parameters: dict[str, Any],
        diff_snapshot: dict[str, Any],
        conversation_id: str | None = None,
        channel: str = "web",
        lifetime: timedelta = PENDING_LIFETIME,
    ) -> tuple[PendingAction, str]:
        """Insert a new pending action. Returns (row, confirmation_token).

        The raw confirmation_token is returned once for the caller to embed
        in the diff preview. Subsequent confirmations look it up by value.
        """
        confirmation_token = secrets.token_urlsafe(32)
        idempotency_key = _idempotency_key(capability, parameters)

        action = PendingAction(
            id=new_id("act"),
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            capability=capability,
            parameters_encrypted=encrypt(json.dumps(parameters)),
            diff_snapshot_json=diff_snapshot,
            confirmation_token=confirmation_token,
            status="pending",
            idempotency_key=idempotency_key,
            channel=channel,
            expires_at=datetime.now(UTC) + lifetime,
        )
        self.db.add(action)
        await self.db.flush()
        return action, confirmation_token

    async def confirm(
        self,
        *,
        confirmation_token: str,
        tenant_id: str,
    ) -> PendingAction:
        """Mark a pending action as confirmed.

        Uses SELECT ... FOR UPDATE to serialise concurrent confirms of the
        same token (defense against double-click). Verifies tenant_id matches
        the requester (cross-tenant confirm = 403 in the route layer; here
        we raise PendingActionInvalid).
        """
        res = await self.db.execute(
            select(PendingAction)
            .where(PendingAction.confirmation_token == confirmation_token)
            .with_for_update()
        )
        action = res.scalar_one_or_none()
        if action is None:
            raise PendingActionInvalid("unknown confirmation token")
        if action.tenant_id != tenant_id:
            raise PendingActionInvalid("token does not belong to this tenant")
        if action.status != "pending":
            raise PendingActionInvalid(f"action is {action.status}, not pending")
        if action.expires_at <= datetime.now(UTC):
            action.status = "expired"
            await self.db.flush()
            raise PendingActionExpired("confirmation window elapsed")

        action.status = "confirmed"
        action.confirmed_at = datetime.now(UTC)
        await self.db.flush()
        return action

    async def cancel(self, *, confirmation_token: str, tenant_id: str) -> PendingAction:
        res = await self.db.execute(
            select(PendingAction).where(
                PendingAction.confirmation_token == confirmation_token
            )
        )
        action = res.scalar_one_or_none()
        if action is None or action.tenant_id != tenant_id:
            raise PendingActionInvalid("unknown confirmation token")
        if action.status not in ("pending", "confirmed"):
            return action  # already terminal
        action.status = "cancelled"
        await self.db.flush()
        return action

    async def mark_executed(
        self,
        *,
        action_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        await self.db.execute(
            update(PendingAction)
            .where(PendingAction.id == action_id)
            .values(
                status="executed",
                executed_at=datetime.now(UTC),
                result_json=result,
            )
        )

    async def find_executed_with_key(
        self, *, tenant_id: str, idempotency_key: str, exclude_id: str
    ) -> PendingAction | None:
        """Return any *other* row already in `executed` status for this
        (tenant, idempotency_key). Used as a belt-and-braces check before
        dispatch: even if our nonce-based keys collide on a parallel write
        race, we'd rather replay the prior result than double-execute."""

        res = await self.db.execute(
            select(PendingAction)
            .where(PendingAction.tenant_id == tenant_id)
            .where(PendingAction.idempotency_key == idempotency_key)
            .where(PendingAction.status == "executed")
            .where(PendingAction.id != exclude_id)
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def mark_failed(self, *, action_id: str, error: str) -> None:
        await self.db.execute(
            update(PendingAction)
            .where(PendingAction.id == action_id)
            .values(status="failed", error_detail=error[:4000])
        )

    async def decrypt_parameters(self, action: PendingAction) -> dict[str, Any]:
        return json.loads(decrypt(action.parameters_encrypted))

    async def sweep_expired(self) -> int:
        """Mark stale `pending` rows as `expired`. Run from a scheduled job."""
        res = await self.db.execute(
            update(PendingAction)
            .where(PendingAction.status == "pending")
            .where(PendingAction.expires_at < datetime.now(UTC))
            .values(status="expired")
        )
        return res.rowcount or 0
