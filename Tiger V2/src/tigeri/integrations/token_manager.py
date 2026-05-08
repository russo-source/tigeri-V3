"""Per-tenant OAuth token store with auto-refresh.

Persists encrypted access + refresh tokens in `tenant_integrations`. On every
fetch, returns a still-valid access token, refreshing via the provider's
refresh-token endpoint when needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.ids import new_id
from tigeri.integrations.encryption import decrypt, encrypt
from tigeri.integrations.models import TenantIntegration


REFRESH_SAFETY_WINDOW = timedelta(minutes=2)


@dataclass
class StoredToken:
    access_token: str
    refresh_token: str
    expires_at: datetime
    meta: dict[str, Any]


async def get(
    session: AsyncSession, tenant_id: str, provider: str
) -> TenantIntegration | None:
    return await session.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == provider,
        )
    )


async def save(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    access_token: str,
    refresh_token: str,
    expires_in_seconds: int,
    meta: dict[str, Any],
) -> TenantIntegration:
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    row = await get(session, tenant_id, provider)
    if row is None:
        row = TenantIntegration(
            id=new_id("ti"),
            tenant_id=tenant_id,
            provider=provider,
            access_token_enc=encrypt(access_token),
            refresh_token_enc=encrypt(refresh_token) if refresh_token else "",
            access_token_expires_at=expires_at,
            meta_json=meta,
        )
        session.add(row)
    else:
        row.access_token_enc = encrypt(access_token)
        if refresh_token:
            row.refresh_token_enc = encrypt(refresh_token)
        row.access_token_expires_at = expires_at
        row.meta_json = {**(row.meta_json or {}), **meta}
        row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


def stored(row: TenantIntegration) -> StoredToken:
    return StoredToken(
        access_token=decrypt(row.access_token_enc),
        refresh_token=decrypt(row.refresh_token_enc) if row.refresh_token_enc else "",
        expires_at=row.access_token_expires_at,
        meta=dict(row.meta_json or {}),
    )


async def get_access_token(
    session: AsyncSession,
    tenant_id: str,
    provider: str,
    *,
    refresh_fn=None,
) -> StoredToken:
    """Return a still-valid access token, refreshing via ``refresh_fn`` when due.

    ``refresh_fn`` is an async callable: ``(refresh_token, meta) -> dict``
    returning the provider's token response (``access_token``, ``refresh_token``,
    ``expires_in``).
    """

    row = await get(session, tenant_id, provider)
    if row is None:
        raise LookupError(f"no {provider} integration for tenant {tenant_id}")

    needs_refresh = datetime.now(UTC) + REFRESH_SAFETY_WINDOW >= row.access_token_expires_at
    if not needs_refresh:
        return stored(row)

    if refresh_fn is None:
        raise RuntimeError(
            f"{provider} access token expired and no refresh_fn supplied"
        )

    refresh_token = decrypt(row.refresh_token_enc) if row.refresh_token_enc else ""
    payload = await refresh_fn(refresh_token, row.meta_json or {})
    row = await save(
        session,
        tenant_id=tenant_id,
        provider=provider,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_in_seconds=int(payload.get("expires_in", 1800)),
        meta=row.meta_json or {},
    )
    return stored(row)
