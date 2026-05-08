"""Tenant-level preferences read off the ``tenants.settings`` JSON column.

Centralises the keys + defaults so callers don't sprinkle string literals
("timezone", "gmail_signature", …) and stale fallbacks throughout the
codebase. Adding a new pref here adds it everywhere it's used.

Why JSON instead of dedicated columns? Tenant settings are sparse and
tenant-specific — most rows won't override most defaults. JSON keeps the
schema change cost at zero each time we add one. Indexed lookups are not
needed (we always read the whole row anyway).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.tenant.models import Tenant


# Default timezone for a freshly-seeded tenant. Asia/Singapore (+08:00, no
# DST) covers the SG-region pilot. Tenants in other regions can override
# via the admin UI / API.
DEFAULT_TIMEZONE = "Asia/Singapore"


# Default signature appended to outbound mail. Empty by default — gets
# applied when the admin sets one.
DEFAULT_GMAIL_SIGNATURE = ""


async def get_tenant_settings(
    session: AsyncSession, tenant_id: str
) -> dict[str, Any]:
    """Return the tenant's settings dict (empty dict if no row / unset)."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return {}
    return tenant.settings or {}


async def get_timezone(session: AsyncSession, tenant_id: str) -> str:
    settings = await get_tenant_settings(session, tenant_id)
    tz = settings.get("timezone")
    if isinstance(tz, str) and tz.strip():
        return tz.strip()
    return DEFAULT_TIMEZONE


async def get_gmail_signature(session: AsyncSession, tenant_id: str) -> str:
    settings = await get_tenant_settings(session, tenant_id)
    sig = settings.get("gmail_signature")
    if isinstance(sig, str):
        return sig
    return DEFAULT_GMAIL_SIGNATURE
