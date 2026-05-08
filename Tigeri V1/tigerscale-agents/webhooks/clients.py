"""Contain clients backend logic."""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from config.db_pool import get_conn
from security.audit import log_action
from auth.deps import require_admin
router = APIRouter()


class ClientCreateRequest(BaseModel):
    """Represent the ClientCreateRequest component and its related behavior."""
    client_id: str
    name: str
    accounting_system: str = "xero"
    storage: str = "onedrive"
    calendar: str = "outlook"
    email: str = "outlook"
    active_agents: list[str] = ["a01_invoice", "a02_expense", "a03_admin", "a04_payment"]
    channels: list[str] = ["whatsapp", "telegram", "email"]


class ClientStatusRequest(BaseModel):
    """Represent the ClientStatusRequest component and its related behavior."""
    client_id: str
    active: bool


@router.post("/admin/clients")
def create_client(body: ClientCreateRequest, x_admin_key: Optional[str] = Header(None)):
    """Create client."""
    _verify_admin(x_admin_key)
    try:
        from config.client_config import save_client_config
        config = {
            "client_id": body.client_id,
            "name": body.name,
            "accounting_system": body.accounting_system,
            "storage": body.storage,
            "calendar": body.calendar,
            "email": body.email,
            "active_agents": body.active_agents,
            "channels": body.channels,
            "approve_email": "",
            "approver_chat_id" : "",
            "approver_whatsapp" :"",
        }
        save_client_config(body.client_id, config)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO clients (client_id, name, active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (client_id) DO UPDATE SET name = EXCLUDED.name
            """, (body.client_id, body.name))
            cur.close()
        log_action(body.client_id, "admin", "client_create", body.client_id, {"status": "created"}, "success")
        return {"status": "created", "client_id": body.client_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Client creation failed")
    


@router.patch("/admin/clients/status")
def set_client_status(
    body: ClientStatusRequest,
    admin: dict = Depends(require_admin),
):
    """Set client status."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE clients SET active = %s
                WHERE client_id = %s
                RETURNING client_id
            """, (body.active, body.client_id))
            row = cur.fetchone()
            cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Client not found")

        action = "activated" if body.active else "revoked"

        log_action(
            client_id=body.client_id,
            agent_name="admin",
            intent=f"client_{action}",
            input_text=body.client_id,
            output={"active": body.active},
            status="success",
        )

        return {"status": action, "client_id": body.client_id}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Status update failed")


@router.get("/admin/clients/{client_id}")
def get_client(
    client_id: str,
    x_admin_key: Optional[str] = Header(None),
):
    """Return client."""
    _verify_admin(x_admin_key)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT client_id, name, active, created_at
                FROM clients WHERE client_id = %s
            """, (client_id,))
            row = cur.fetchone()
            cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Client not found")

        return {
            "client_id": row[0],
            "name": row[1],
            "active": row[2],
            "created_at": str(row[3]),
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch client")


@router.delete("/admin/clients/{client_id}")
def delete_client(
    client_id: str,
    x_admin_key: Optional[str] = Header(None),
):
    """Delete client."""
    _verify_admin(x_admin_key)

    try:
        from config.client_config import save_client_config
        save_client_config(client_id, {"active": False})

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE clients SET active = FALSE WHERE client_id = %s",
                (client_id,)
            )
            cur.close()

        log_action(
            client_id=client_id,
            agent_name="admin",
            intent="client_delete",
            input_text=client_id,
            output={"status": "deleted"},
            status="success",
        )

        return {"status": "deleted", "client_id": client_id}

    except Exception:
        raise HTTPException(status_code=500, detail="Delete failed")


def _verify_admin(key: Optional[str]):
    """Execute verify admin."""
    from config.settings import settings
    if not key or key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Unauthorised")