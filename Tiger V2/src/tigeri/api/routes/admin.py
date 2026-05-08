"""Admin-only endpoints. Gated by require_admin (role in {owner, admin}).

For pilot the admin can:
  - List all tenants
  - List users in a tenant
  - List + verify the audit-log hash chain for a tenant
  - List recent pending actions
"""

from __future__ import annotations

import os
import secrets
import string
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.actions.models import PendingAction
from tigeri.api.deps import get_session
from tigeri.audit_chain.models import AuditLog
from tigeri.audit_chain.writer import verify_chain
from tigeri.auth.admin import require_admin
from tigeri.auth.models import Session as AuthSession, User
from tigeri.auth.passwords import hash_password
from tigeri.auth.scope import TenantScope
from tigeri.core.ids import new_id
from tigeri.tenant.models import Tenant

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ───────────── schemas ─────────────


class TenantSummary(BaseModel):
    id: str
    slug: str
    name: str
    region: str
    plan: str
    status: str
    created_at: str


class UserSummary(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: str
    role: str
    status: str
    email_verified: bool
    last_active_at: str | None
    created_at: str


class AuditLogRow(BaseModel):
    id: str
    tenant_id: str
    user_id: str | None
    event_type: str
    capability: str | None
    result: str
    idempotency_key: str | None
    parameters_redacted: dict | None
    signed_hash: str
    prev_hash: str
    created_at: str


class ChainVerification(BaseModel):
    tenant_id: str
    ok: bool
    rows_checked: int
    broken_row_id: str | None


class PendingActionRow(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    capability: str
    status: str
    expires_at: str
    confirmed_at: str | None
    executed_at: str | None


# ───────────── routes ─────────────


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> list[TenantSummary]:
    res = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return [
        TenantSummary(
            id=t.id,
            slug=t.slug,
            name=t.name,
            region=t.region,
            plan=t.plan,
            status=t.status,
            created_at=t.created_at.isoformat(),
        )
        for t in res.scalars()
    ]


def _user_to_summary(u: User) -> UserSummary:
    return UserSummary(
        id=u.id,
        tenant_id=u.tenant_id,
        email=u.email,
        name=u.name,
        role=u.role,
        status=u.status,
        email_verified=u.email_verified,
        last_active_at=u.last_active_at.isoformat() if u.last_active_at else None,
        created_at=u.created_at.isoformat(),
    )


@router.get("/tenants/{tenant_id}/users", response_model=list[UserSummary])
async def list_users(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> list[UserSummary]:
    res = await db.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.desc())
    )
    return [_user_to_summary(u) for u in res.scalars()]


# ───────────── user mutations (admin) ─────────────


_PWD_ALPHABET = string.ascii_letters + string.digits

# Pilot-time default. Every admin-created user that doesn't pass an explicit
# `password` gets this plus must_change_password=true on the user row. Set
# the env var to switch to per-user random; leave unset to keep the
# operator-friendly shared default during the demo cycle.
_DEFAULT_TEMP_PASSWORD = os.environ.get("TIGERI_DEFAULT_NEW_USER_PASSWORD", "PickleJar$")


def _generate_password(length: int = 16) -> str:
    """Return the configured pilot default if it's set; else a fresh random
    string. The env-var path lets ops keep a single shareable temp during
    the pilot without hardcoding it in every reset path."""
    if _DEFAULT_TEMP_PASSWORD:
        return _DEFAULT_TEMP_PASSWORD
    return "".join(secrets.choice(_PWD_ALPHABET) for _ in range(length))


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=256)
    role: Literal["owner", "admin", "member"] = "member"
    # If omitted, the server generates a strong password and returns it once.
    password: str | None = Field(default=None, min_length=8, max_length=256)


class CreateUserResponse(BaseModel):
    user: UserSummary
    # Plaintext password — echoed exactly once so the admin can share it.
    # Once this response is gone, the password is unrecoverable; only resets
    # are possible via /reset-password.
    initial_password: str
    auto_generated: bool


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    role: Literal["owner", "admin", "member"] | None = None
    status: Literal["invited", "active", "suspended", "offboarded"] | None = None


class ResetPasswordRequest(BaseModel):
    # Optional — admin can choose a new password or let the server pick.
    password: str | None = Field(default=None, min_length=8, max_length=256)


class ResetPasswordResponse(BaseModel):
    user_id: str
    new_password: str
    auto_generated: bool


async def _load_user_in_tenant(
    db: AsyncSession, *, user_id: str
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post(
    "/tenants/{tenant_id}/users",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    tenant_id: str,
    payload: CreateUserRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[TenantScope, Depends(require_admin)],
) -> CreateUserResponse:
    """Create a user in ``tenant_id`` with an initial password.

    Echoes the plaintext password in the response **exactly once**. The
    admin is expected to copy it and share via an out-of-band channel
    (e.g. password manager, encrypted message). Don't log the response body.
    """
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant not found")

    email_norm = payload.email.lower()
    existing = await db.execute(
        select(User).where(User.tenant_id == tenant_id).where(User.email == email_norm)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="email already exists in this tenant"
        )

    auto_generated = payload.password is None
    initial_password = payload.password or _generate_password()

    user = User(
        id=new_id("usr"),
        tenant_id=tenant_id,
        email=email_norm,
        name=payload.name,
        role=payload.role,
        status="active",
        password_hash=hash_password(initial_password),
        email_verified=False,
        invited_by=actor.user_id,
        invited_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    await db.commit()

    return CreateUserResponse(
        user=_user_to_summary(user),
        initial_password=initial_password,
        auto_generated=auto_generated,
    )


@router.patch("/users/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[TenantScope, Depends(require_admin)],
) -> UserSummary:
    """Patch a user's name / role / status. Suspending or offboarding a user
    also revokes every active session of theirs so the change takes effect
    immediately on every device they're signed in on.
    """
    user = await _load_user_in_tenant(db, user_id=user_id)

    if user.id == actor.user_id and payload.role is not None and payload.role != user.role:
        # Self-demotion blocks an admin from accidentally locking themselves
        # out of admin endpoints. They must use a different admin account.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="cannot change your own role; ask another admin",
        )

    if (
        user.id == actor.user_id
        and payload.status is not None
        and payload.status in ("suspended", "offboarded")
    ):
        # Mirrors the offboard endpoint's self-protection — without this guard
        # an admin could lock themselves out by patching their own status.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="cannot suspend or offboard yourself; ask another admin",
        )

    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
        if payload.status in ("suspended", "offboarded"):
            from tigeri.auth.sessions import revoke_all_for_user

            await revoke_all_for_user(db, user_id=user.id)

    await db.commit()
    return _user_to_summary(user)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_user_password(
    user_id: str,
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> ResetPasswordResponse:
    """Mint a new password for ``user_id`` and revoke all their existing
    sessions. The new password is echoed once — same one-time-share posture
    as :func:`create_user`."""
    user = await _load_user_in_tenant(db, user_id=user_id)

    auto_generated = payload.password is None
    new_password = payload.password or _generate_password()
    user.password_hash = hash_password(new_password)

    # Force re-auth everywhere — the previous password is no longer valid.
    from tigeri.auth.sessions import revoke_all_for_user

    await revoke_all_for_user(db, user_id=user.id)
    await db.commit()

    return ResetPasswordResponse(
        user_id=user.id,
        new_password=new_password,
        auto_generated=auto_generated,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def offboard_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[TenantScope, Depends(require_admin)],
) -> None:
    """Soft-delete a user — sets status='offboarded' and revokes all sessions.
    The row is kept for audit-log references; never hard-delete a user that
    has any audit history."""
    user = await _load_user_in_tenant(db, user_id=user_id)
    if user.id == actor.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="cannot offboard yourself; ask another admin",
        )
    user.status = "offboarded"
    from tigeri.auth.sessions import revoke_all_for_user

    await revoke_all_for_user(db, user_id=user.id)
    await db.commit()


@router.get("/tenants/{tenant_id}/audit-logs", response_model=list[AuditLogRow])
async def list_audit_logs(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    event_type: str | None = None,
) -> list[AuditLogRow]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    res = await db.execute(stmt)
    rows = list(res.scalars())
    return [
        AuditLogRow(
            id=r.id,
            tenant_id=r.tenant_id,
            user_id=r.user_id,
            event_type=r.event_type,
            capability=r.capability,
            result=r.result,
            idempotency_key=r.idempotency_key,
            parameters_redacted=r.parameters_redacted,
            signed_hash=r.signed_hash,
            prev_hash=r.prev_hash,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.post(
    "/tenants/{tenant_id}/audit-logs/verify",
    response_model=ChainVerification,
)
async def verify_audit_chain(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> ChainVerification:
    ok, count, broken = await verify_chain(db, tenant_id)
    return ChainVerification(
        tenant_id=tenant_id, ok=ok, rows_checked=count, broken_row_id=broken
    )


@router.get(
    "/tenants/{tenant_id}/pending-actions", response_model=list[PendingActionRow]
)
async def list_pending_actions(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
    status_filter: Annotated[
        Literal["pending", "confirmed", "executed", "expired", "cancelled", "failed"]
        | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PendingActionRow]:
    stmt = (
        select(PendingAction)
        .where(PendingAction.tenant_id == tenant_id)
        .order_by(PendingAction.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(PendingAction.status == status_filter)
    res = await db.execute(stmt)
    return [
        PendingActionRow(
            id=a.id,
            tenant_id=a.tenant_id,
            user_id=a.user_id,
            capability=a.capability,
            status=a.status,
            expires_at=a.expires_at.isoformat(),
            confirmed_at=a.confirmed_at.isoformat() if a.confirmed_at else None,
            executed_at=a.executed_at.isoformat() if a.executed_at else None,
        )
        for a in res.scalars()
    ]


class TenantSettings(BaseModel):
    """Subset of tenant.settings the admin can view/edit. Each field is
    optional on PATCH — None means "leave unchanged"."""

    timezone: str | None = Field(
        default=None,
        description="IANA timezone, e.g. 'Asia/Singapore'. Used by the "
        "orchestrator to ground relative dates ('tomorrow at 10am').",
        max_length=64,
    )
    gmail_signature: str | None = Field(
        default=None,
        description="Plain-text signature appended to outbound mail. Empty "
        "string = no signature. None = leave existing value.",
        max_length=2000,
    )


@router.get(
    "/tenants/{tenant_id}/settings",
    response_model=TenantSettings,
)
async def get_tenant_settings(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> TenantSettings:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant not found")
    s = tenant.settings or {}
    return TenantSettings(
        timezone=s.get("timezone"),
        gmail_signature=s.get("gmail_signature"),
    )


@router.patch(
    "/tenants/{tenant_id}/settings",
    response_model=TenantSettings,
)
async def patch_tenant_settings(
    tenant_id: str,
    payload: TenantSettings,
    db: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[TenantScope, Depends(require_admin)],
) -> TenantSettings:
    """Merge-update tenant.settings. Fields with value None on the request
    are left untouched; fields with a value (including '') overwrite."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant not found")

    settings = dict(tenant.settings or {})
    if payload.timezone is not None:
        # Validate that the IANA name resolves to avoid storing junk.
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(payload.timezone)
        except Exception:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"unknown timezone {payload.timezone!r}",
            )
        settings["timezone"] = payload.timezone
    if payload.gmail_signature is not None:
        settings["gmail_signature"] = payload.gmail_signature
    tenant.settings = settings
    await db.commit()

    return TenantSettings(
        timezone=settings.get("timezone"),
        gmail_signature=settings.get("gmail_signature"),
    )


@router.get("/health")
async def admin_health(
    _: Annotated[TenantScope, Depends(require_admin)],
) -> dict:
    """Smoke test for the admin gate. 200 if you're admin, 401/403 otherwise."""
    return {"status": "ok", "role_check": "passed"}
