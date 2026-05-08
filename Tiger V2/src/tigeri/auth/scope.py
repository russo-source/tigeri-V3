"""TenantScope resolver — the FastAPI dependency every authed route should use.

Resolution order:
  1. Cookie `tigeri_session` -> sessions table -> users -> tenants.
     Verifies tenant.status='active' and user.status='active'. 401 otherwise.
  2. Legacy headers `X-Tigeri-Tenant-Id` + `X-Tigeri-User-Id`. No DB validation;
     this is the pre-Phase-1 contract. Kept so the existing frontend works
     unchanged during the rollout. Role defaults to 'member'.
  3. Neither -> 401.

Phase 2 will flip the frontend to cookies and the header path will be removed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.api.deps import get_session
from tigeri.auth.models import User
from tigeri.auth.sessions import COOKIE_NAME, get_active_session, touch_session
from tigeri.tenant.models import Tenant


@dataclass(slots=True)
class TenantScope:
    tenant_id: str
    user_id: str
    role: str
    session_id: str | None  # None when resolved from legacy headers


async def _resolve_from_cookie(db: AsyncSession, raw_token: str) -> TenantScope | None:
    session = await get_active_session(db, raw_token)
    if session is None:
        return None

    res = await db.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == session.user_id)
    )
    row = res.first()
    if row is None:
        return None
    user, tenant = row

    if tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="tenant suspended")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="user inactive")

    await touch_session(db, session)
    user.last_active_at = datetime.now(UTC)

    return TenantScope(
        tenant_id=tenant.id,
        user_id=user.id,
        role=user.role,
        session_id=session.id,
    )


async def _resolve_from_headers(
    db: AsyncSession, tenant_id: str | None, user_id: str | None
) -> TenantScope | None:
    """Header-auth fallback. Used by curl-style integration tests and the
    legacy /sign-in DEMO tab. Validates that the supplied tenant_id exists
    in the DB — otherwise stale localStorage values like the dev fixture
    'tnt_demo' would build a 'valid' scope object and FK-violate on the
    very first write (pending_actions, audit_logs, …)."""
    if not tenant_id:
        return None

    from tigeri.tenant.models import Tenant as _Tenant

    tenant = await db.get(_Tenant, tenant_id)
    if tenant is None:
        # Don't echo the bad id back in the error — clients sometimes have
        # stale fixture ids like 'tnt_demo' from local-dev seeds; forcing
        # the user to clear those is exactly the desired UX here.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid tenant id; sign in again",
        )
    return TenantScope(
        tenant_id=tenant.id,
        user_id=user_id or "anonymous",
        role="member",
        session_id=None,
    )


async def get_scope_optional(
    db: Annotated[AsyncSession, Depends(get_session)],
    tigeri_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    x_tigeri_tenant_id: Annotated[str | None, Header(alias="X-Tigeri-Tenant-Id")] = None,
    x_tigeri_user_id: Annotated[str | None, Header(alias="X-Tigeri-User-Id")] = None,
) -> TenantScope | None:
    """Returns a scope if one is resolvable, otherwise None. Does not raise
    for missing credentials, but does raise 403 for suspended tenant/user."""
    if tigeri_session:
        scope = await _resolve_from_cookie(db, tigeri_session)
        if scope is not None:
            return scope

    return await _resolve_from_headers(db, x_tigeri_tenant_id, x_tigeri_user_id)


async def get_scope(
    scope: Annotated[TenantScope | None, Depends(get_scope_optional)],
) -> TenantScope:
    """Required-auth variant. Raises 401 if no scope can be resolved."""
    if scope is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return scope
