"""Auth endpoints: sign-up, sign-in, sign-out, me.

These are net-new in Phase 1 — the existing frontend continues to use header
auth via tigeri.api.deps.get_tenant_id. A future frontend cutover will switch
to these endpoints + the tigeri_session cookie.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.api.deps import get_session
from tigeri.auth.models import User
from tigeri.auth.passwords import hash_password, verify_password
from tigeri.auth.scope import TenantScope, get_scope_optional
from tigeri.auth.sessions import (
    COOKIE_NAME,
    SESSION_LIFETIME,
    create_session,
    revoke_session,
)
from tigeri.core.config import get_settings
from tigeri.core.ids import new_id
from tigeri.core.rate_limit import sign_in_limiter, sign_up_limiter
from tigeri.tenant.models import Tenant

router = APIRouter(prefix="/auth", tags=["auth"])

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower()).strip("-")
    return s[:64] or "tenant"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    candidate = base
    suffix = 2
    while True:
        existing = await db.execute(select(Tenant.id).where(Tenant.slug == candidate))
        if existing.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def _set_session_cookie(response: Response, raw_token: str) -> None:
    """Set the session cookie.

    Cross-origin frontend (localhost:3000) talking to an HTTPS backend
    (sslip.io) requires SameSite=None;Secure to send the cookie back. We use
    that everywhere — when env=local AND the backend is plain http, set
    SameSite=Lax (no Secure) so dev still works without HTTPS.
    """
    settings = get_settings()
    if settings.public_api_base_url.startswith("https://"):
        samesite: str = "none"
        secure = True
    else:
        samesite = "lax"
        secure = False
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


# ───────────────── schemas ─────────────────


class SignUpRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=256)
    email: EmailStr
    name: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=8, max_length=256)


class SignInRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ScopeResponse(BaseModel):
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    user_id: str
    user_email: str
    user_name: str
    role: str
    via: Literal["cookie", "header"]
    # True when the user must change their password before any other API
    # call will succeed. Frontend reads this on /sign-in and /me and routes
    # to /change-password until it clears.
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


# ───────────────── routes ─────────────────


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honouring the nginx X-Forwarded-For header.

    Trusts only the leftmost address — which is the originating client per
    RFC 7239 — and ignores the rest. Falls back to request.client.host when
    no forwarding header is present.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


@router.post("/sign-up", response_model=ScopeResponse, status_code=status.HTTP_201_CREATED)
async def sign_up(
    payload: SignUpRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ScopeResponse:
    ip = _client_ip(request)
    allowed, retry = sign_up_limiter.hit(ip)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"too many sign-up attempts; retry in {retry}s",
            headers={"Retry-After": str(retry)},
        )

    base_slug = _slugify(payload.tenant_name)
    slug = await _unique_slug(db, base_slug)

    tenant = Tenant(
        id=new_id("tnt"),
        name=payload.tenant_name,
        slug=slug,
        region="sg",
        plan="pilot",
        status="active",
        settings={},
    )
    db.add(tenant)
    await db.flush()

    now = datetime.now(UTC)
    user = User(
        id=new_id("usr"),
        tenant_id=tenant.id,
        email=payload.email.lower(),
        name=payload.name,
        role="owner",
        status="active",
        password_hash=hash_password(payload.password),
        email_verified=False,
        # Stamp last_active_at on creation so analytics + cleanup queries
        # never see a NULL for an account that just signed in. sign_in()
        # already sets this; sign_up() used to forget it.
        last_active_at=now,
    )
    db.add(user)
    await db.flush()

    # Best-effort: pre-populate the new tenant with demo invoices /
    # expenses / settings (timezone=Asia/Singapore by default) so the
    # dashboard isn't empty on day zero. Never blocks sign-up.
    try:
        from tigeri.tenant.seed_demo import seed_demo_data

        await seed_demo_data(db, tenant_id=tenant.id, owner_user_id=user.id)
    except Exception as e:  # noqa: BLE001
        # Log with tenant context so operators can spot incomplete demo
        # data on a real sign-up. Sign-up still succeeds — demo data is
        # cosmetic, not load-bearing.
        import logging

        logging.getLogger(__name__).warning(
            "demo seed failed for new tenant",
            extra={"tenant_id": tenant.id, "error": f"{type(e).__name__}: {e}"},
        )

    _, raw_token = await create_session(
        db,
        user_id=user.id,
        tenant_id=tenant.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_session_cookie(response, raw_token)

    return ScopeResponse(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        role=user.role,
        via="cookie",
        must_change_password=bool(user.must_change_password),
    )


@router.post("/sign-in", response_model=ScopeResponse)
async def sign_in(
    payload: SignInRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ScopeResponse:
    ip = _client_ip(request)
    rate_key = (ip, payload.email.lower())
    allowed, retry = sign_in_limiter.hit(*rate_key)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"too many sign-in attempts; retry in {retry}s",
            headers={"Retry-After": str(retry)},
        )

    res = await db.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(Tenant.slug == payload.tenant_slug)
        .where(User.email == payload.email.lower())
    )
    row = res.first()
    if row is None:
        # Same error shape as bad password — don't leak whether the email exists.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    user, tenant = row

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    # Successful auth — clear the bucket so a typo-recovering user isn't
    # penalised on subsequent logins.
    sign_in_limiter.reset(*rate_key)
    if tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="tenant suspended")
    if user.status not in ("active", "invited"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="user inactive")

    user.last_active_at = datetime.now(UTC)

    _, raw_token = await create_session(
        db,
        user_id=user.id,
        tenant_id=tenant.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_session_cookie(response, raw_token)

    return ScopeResponse(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        role=user.role,
        via="cookie",
        must_change_password=bool(user.must_change_password),
    )


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    tigeri_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> Response:
    if tigeri_session:
        await revoke_session(db, tigeri_session)
    _clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=ScopeResponse)
async def me(
    db: Annotated[AsyncSession, Depends(get_session)],
    scope: Annotated[TenantScope | None, Depends(get_scope_optional)],
) -> ScopeResponse:
    if scope is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    res = await db.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == scope.user_id)
        .where(Tenant.id == scope.tenant_id)
    )
    row = res.first()
    if row is None:
        # Header-resolved scope where the user/tenant rows don't yet exist.
        # Pre-Phase-1 frontend hits this — return a synthetic response so the
        # client can still introspect.
        return ScopeResponse(
            tenant_id=scope.tenant_id,
            tenant_slug=scope.tenant_id,
            tenant_name=scope.tenant_id,
            user_id=scope.user_id,
            user_email="",
            user_name=scope.user_id,
            role=scope.role,
            via="header",
        )
    user, tenant = row
    return ScopeResponse(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        role=user.role,
        via="cookie" if scope.session_id else "header",
        must_change_password=bool(user.must_change_password),
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
    scope: Annotated[TenantScope | None, Depends(get_scope_optional)],
) -> Response:
    """Verify the current password, set a new one, clear the must-change flag.

    Requires an active session — even when ``must_change_password`` is true,
    sign-in still mints a cookie so the user can call THIS endpoint. Every
    other authed call is blocked by middleware while the flag is set."""

    if scope is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="new password must differ from current password",
        )

    user = await db.scalar(select(User).where(User.id == scope.user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.updated_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
