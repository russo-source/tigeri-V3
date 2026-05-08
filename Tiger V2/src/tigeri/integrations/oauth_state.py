"""OAuth state-nonce store — CSRF protection for the connect flow.

Replaces the previous ``state = "{tenant_id}:{nonce}"`` scheme where the
callback simply trusted whatever tenant_id arrived in the state. The audit
caught that as a textbook account-hijack vector: an attacker initiates an
OAuth flow, swaps the state in transit (or starts on a victim tenant_id),
and binds their provider account to the victim.

Now: the route generates a random nonce, persists ``(nonce, tenant_id,
provider, user_id, expires_at)``, and uses **only the nonce** as the OAuth
state. The callback looks up the nonce, validates the provider matches, and
deletes the row (one-shot use). Tenant_id is recovered from the row, not
from the URL.

Lifetime is 10 minutes; expired rows are skipped on lookup and swept by a
periodic job (or just left until the next consume — table stays small).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base

STATE_LIFETIME = timedelta(minutes=10)


class InvalidStateError(Exception):
    """Raised when an OAuth callback presents a state that does not exist,
    has expired, or was issued for a different provider."""


class OAuthState(Base):
    """One row per in-flight OAuth /connect request."""

    __tablename__ = "oauth_states"

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


async def issue(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    user_id: str | None = None,
) -> str:
    """Persist a fresh state nonce and return its value.

    Caller embeds the nonce as the OAuth ``state`` parameter; nothing else
    about the in-flight flow is exposed to the user-agent.
    """
    nonce = secrets.token_urlsafe(32)
    row = OAuthState(
        nonce=nonce,
        tenant_id=tenant_id,
        provider=provider,
        user_id=user_id,
        expires_at=datetime.now(UTC) + STATE_LIFETIME,
    )
    db.add(row)
    await db.commit()
    return nonce


async def consume(
    db: AsyncSession,
    *,
    state_nonce: str,
    provider: str,
) -> str:
    """Look up and atomically delete the state nonce. Returns its tenant_id.

    Raises ``InvalidStateError`` for any of:
      - unknown nonce
      - provider mismatch (issued for a different provider)
      - expired (>STATE_LIFETIME old)
    """
    if not state_nonce:
        raise InvalidStateError("missing OAuth state")

    res = await db.execute(select(OAuthState).where(OAuthState.nonce == state_nonce))
    row = res.scalar_one_or_none()
    if row is None:
        raise InvalidStateError("unknown OAuth state")

    # One-shot consume regardless of validity below — prevents an attacker
    # from probing the same nonce repeatedly.
    await db.execute(delete(OAuthState).where(OAuthState.nonce == state_nonce))

    if row.provider != provider:
        raise InvalidStateError(
            f"state issued for {row.provider!r}, callback hit {provider!r}"
        )
    if row.expires_at <= datetime.now(UTC):
        raise InvalidStateError("OAuth state expired")
    return row.tenant_id


async def cleanup_expired(db: AsyncSession) -> int:
    """Sweep job. Returns rows deleted."""
    res = await db.execute(
        delete(OAuthState).where(OAuthState.expires_at < datetime.now(UTC))
    )
    return res.rowcount or 0
