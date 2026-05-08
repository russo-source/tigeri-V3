"""Contain approver config backend logic."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from auth.deps import get_current_user
from config.client_config import get_client_config, save_client_config
from security.audit import log_action

router = APIRouter()



class ApproverConfigResponse(BaseModel):
    """Represent the ApproverConfigResponse component and its related behavior."""
    approver_chat_id:   Optional[str] = None   # Telegram chat ID
    approver_whatsapp:  Optional[str] = None   # E.164, no '+'
    approve_email:      Optional[str] = None   # email address


class ApproverConfigUpdate(BaseModel):
    """Represent the ApproverConfigUpdate component and its related behavior."""
    approver_chat_id:   Optional[str]      = None
    approver_whatsapp:  Optional[str]      = None
    approve_email:      Optional[str]      = None


@router.get("/api/v1/client/approver-config", response_model=ApproverConfigResponse)
def get_approver_config(user: dict = Depends(get_current_user)):
    """Return approver config."""
    client_id = user.get("client_id")
    if not client_id:
        raise HTTPException(status_code=403, detail="No client associated with this account")

    try:
        config = get_client_config(client_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Client config not found")

    return ApproverConfigResponse(
        approver_chat_id  = config.get("approver_chat_id") or config.get("approve_chat_id"),
        approver_whatsapp = config.get("approver_whatsapp"),
        approve_email     = config.get("approve_email"),
    )


@router.patch("/api/v1/client/approver-config", response_model=ApproverConfigResponse)
def update_approver_config(
    body: ApproverConfigUpdate,
    user: dict = Depends(get_current_user),
):
    """Update approver config."""
    client_id = user.get("client_id")
    if not client_id:
        raise HTTPException(status_code=403, detail="No client associated with this account")

    try:
        config = get_client_config(client_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Client config not found")

    updates = body.model_dump(exclude_unset=True)

    if "approver_chat_id" in updates:
        config.pop("approve_chat_id", None)

    config.update(updates)

    try:
        save_client_config(client_id, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to save config")

    log_action(
        client_id, "client_config", "update_approver_config",
        str(list(updates.keys())), {"updated_keys": list(updates.keys())}, "success",
    )

    return ApproverConfigResponse(
        approver_chat_id  = config.get("approver_chat_id"),
        approver_whatsapp = config.get("approver_whatsapp"),
        approve_email     = config.get("approve_email"),
    )