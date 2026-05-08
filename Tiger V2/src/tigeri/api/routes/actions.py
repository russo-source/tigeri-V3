"""Confirm / cancel routes for pending write actions.

The orchestrator stops short of running write tools and proposes them via
``tigeri.actions.PendingActionService``. The user clicks Confirm in the chat
UI; that POSTs here. We then:
  1. Mark the action confirmed (FOR UPDATE row lock — defense against
     double-click / network retry).
  2. Decrypt the saved parameters.
  3. Dispatch the capability through ``tigeri.actions.dispatch_capability``.
  4. Mark executed and write a hash-chain audit entry — both success and
     failure surface here, never silently swallowed.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.actions.dispatch import UnknownCapabilityError, dispatch_capability
from tigeri.actions.service import (
    PendingActionExpired,
    PendingActionInvalid,
    PendingActionService,
)
from tigeri.api.deps import get_session
from tigeri.audit_chain.writer import AuditChainWriter, AuditEntry
from tigeri.auth.scope import TenantScope, get_scope
from tigeri.core.config import get_settings

router = APIRouter(prefix="/actions", tags=["actions"])


class ConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=8, max_length=256)


class ActionResponse(BaseModel):
    id: str
    capability: str
    status: str
    confirmed_at: str | None
    executed_at: str | None
    result: dict[str, Any] | None = None
    error_detail: str | None = None


def _to_response(action, result: dict[str, Any] | None = None) -> ActionResponse:  # noqa: ANN001
    return ActionResponse(
        id=action.id,
        capability=action.capability,
        status=action.status,
        confirmed_at=action.confirmed_at.isoformat() if action.confirmed_at else None,
        executed_at=action.executed_at.isoformat() if action.executed_at else None,
        result=result if result is not None else action.result_json,
        error_detail=action.error_detail,
    )


@router.post("/confirm", response_model=ActionResponse)
async def confirm(
    payload: ConfirmRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    scope: Annotated[TenantScope, Depends(get_scope)],
) -> ActionResponse:
    svc = PendingActionService(db)
    audit = AuditChainWriter(db)

    # ---- Phase A: mark confirmed (atomic) -----------------------------
    try:
        action = await svc.confirm(
            confirmation_token=payload.confirmation_token,
            tenant_id=scope.tenant_id,
        )
    except PendingActionExpired:
        await audit.write(
            AuditEntry(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
                event_type="action_expired",
                result="expired",
            )
        )
        raise HTTPException(status.HTTP_410_GONE, detail="confirmation window elapsed")
    except PendingActionInvalid as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    await audit.write(
        AuditEntry(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            event_type="action_confirmed",
            capability=action.capability,
            result="success",
            idempotency_key=action.idempotency_key,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )

    # ---- Phase B: decrypt parameters and dispatch the capability ------
    try:
        parameters = await svc.decrypt_parameters(action)
    except Exception as e:  # noqa: BLE001
        await svc.mark_failed(action_id=action.id, error=f"decrypt: {e}")
        await audit.write(
            AuditEntry(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail=f"decrypt: {e}",
            )
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="failed to decrypt parameters"
        )

    # Defensive: if a prior action already executed under the same
    # idempotency_key (race or pre-fix legacy data), short-circuit and
    # return its result instead of re-running the side effect.
    duplicate = await svc.find_executed_with_key(
        tenant_id=scope.tenant_id,
        idempotency_key=action.idempotency_key,
        exclude_id=action.id,
    )
    if duplicate is not None:
        await svc.mark_failed(
            action_id=action.id,
            error=f"duplicate of {duplicate.id}; previous result returned",
        )
        await audit.write(
            AuditEntry(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
                event_type="capability_duplicate_replay",
                capability=action.capability,
                result="success",
                idempotency_key=action.idempotency_key,
            )
        )
        return _to_response(duplicate, result=duplicate.result_json)

    public_base = get_settings().public_api_base_url
    try:
        result = await dispatch_capability(
            capability=action.capability,
            parameters=parameters,
            session=db,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            public_base_url=public_base,
        )
    except UnknownCapabilityError:
        await svc.mark_failed(action_id=action.id, error="unknown capability")
        await audit.write(
            AuditEntry(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail="unknown capability",
            )
        )
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"unknown capability {action.capability}"
        )
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        await svc.mark_failed(action_id=action.id, error=err)
        await audit.write(
            AuditEntry(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail=err[:500],
                idempotency_key=action.idempotency_key,
            )
        )
        return _to_response(action, result={"error": err})

    await svc.mark_executed(action_id=action.id, result=result)
    await audit.write(
        AuditEntry(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            event_type="capability_invoked",
            capability=action.capability,
            result="success",
            idempotency_key=action.idempotency_key,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )

    # mark_executed updated the DB; sync the in-memory row so the response
    # reflects the new state without re-querying.
    action.status = "executed"
    return _to_response(action, result=result)


@router.post("/cancel", response_model=ActionResponse)
async def cancel(
    payload: ConfirmRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    scope: Annotated[TenantScope, Depends(get_scope)],
) -> ActionResponse:
    svc = PendingActionService(db)
    audit = AuditChainWriter(db)
    try:
        action = await svc.cancel(
            confirmation_token=payload.confirmation_token,
            tenant_id=scope.tenant_id,
        )
    except PendingActionInvalid as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    await audit.write(
        AuditEntry(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            event_type="action_cancelled",
            capability=action.capability,
            result="cancelled",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    return _to_response(action)
