"""Contain channels backend logic."""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from config.db_pool import get_conn
from security.audit import log_action
from config.channel_registry import register_channel_token, resolve_client_id

router = APIRouter()


class WhatsAppConnectRequest(BaseModel):
    """Represent the WhatsAppConnectRequest component and its related behavior."""
    client_id: str
    phone_number: str
    api_key: str


class TelegramConnectRequest(BaseModel):
    """Represent the TelegramConnectRequest component and its related behavior."""
    client_id: str
    bot_token: str


class EmailConnectRequest(BaseModel):
    """Represent the EmailConnectRequest component and its related behavior."""
    client_id: str
    provider: str
    access_token: str
    refresh_token: Optional[str] = None


@router.post("/channels/connect/whatsapp")
def connect_whatsapp(
    body: WhatsAppConnectRequest,
    x_admin_key: Optional[str] = Header(None),
):
    """Execute connect whatsapp."""
    _verify_admin(x_admin_key)

    try:
        from integrations.token_manager import bootstrap_token
        bootstrap_token(
            service=f"whatsapp:{body.client_id}",
            access_token=body.api_key,
            expires_in=86400 * 365,
            refresh_token="",
        )

        register_channel_token("whatsapp", body.api_key, body.client_id)
        
        _update_channel_config(body.client_id, "whatsapp", {
            "phone_number": body.phone_number,
            "connected": True,
        })

        log_action(body.client_id, "channel", "whatsapp_connect",
                   body.client_id, {"phone": body.phone_number}, "success")

        return {"status": "connected", "channel": "whatsapp", "client_id": body.client_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail="WhatsApp connect failed")


@router.post("/channels/connect/telegram")
def connect_telegram(
    body: TelegramConnectRequest,
    x_admin_key: Optional[str] = Header(None),
):
    """Execute connect telegram."""
    _verify_admin(x_admin_key)

    try:
        import httpx
        resp = httpx.get(
            f"https://api.telegram.org/bot{body.bot_token}/getMe",
            timeout=5,
        )
        resp.raise_for_status()
        bot_info = resp.json().get("result", {})

        from integrations.token_manager import bootstrap_token
        bootstrap_token(
            service=f"telegram:{body.client_id}",
            access_token=body.bot_token,
            expires_in=86400 * 365,
            refresh_token="",
        )
        
        register_channel_token("telegram", body.bot_token, body.client_id)
        
        _update_channel_config(body.client_id, "telegram", {
            "bot_username": bot_info.get("username"),
            "connected": True,
        })

        log_action(body.client_id, "channel", "telegram_connect",
                   body.client_id, {"bot": bot_info.get("username")}, "success")

        return {
            "status": "connected",
            "channel": "telegram",
            "bot_username": bot_info.get("username"),
            "client_id": body.client_id,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail="Telegram connect failed")


@router.post("/channels/connect/email")
def connect_email(
    body: EmailConnectRequest,
    x_admin_key: Optional[str] = Header(None),
):
    """Execute connect email."""
    _verify_admin(x_admin_key)

    try:
        from integrations.token_manager import bootstrap_token
        bootstrap_token(
            service=body.provider,
            access_token=body.access_token,
            expires_in=3600,
            refresh_token=body.refresh_token or "",
        )
        
        register_channel_token("email", body.access_token, body.client_id)

        _update_channel_config(body.client_id, "email", {
            "provider": body.provider,
            "connected": True,
        })

        log_action(body.client_id, "channel", "email_connect",
                   body.client_id, {"provider": body.provider}, "success")

        return {"status": "connected", "channel": "email", "client_id": body.client_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail="Email connect failed")


@router.get("/channels/status/{client_id}")
def channel_status(
    client_id: str,
    x_admin_key: Optional[str] = Header(None),
):
    """Execute channel status."""
    _verify_admin(x_admin_key)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT channel_config FROM clients WHERE client_id = %s",
                (client_id,)
            )
            row = cur.fetchone()
            cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Client not found")

        return {
            "client_id": client_id,
            "channels": row[0] or {},
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch channel status")


@router.delete("/channels/disconnect/{client_id}/{channel}")
def disconnect_channel(
    client_id: str,
    channel: str,
    x_admin_key: Optional[str] = Header(None),
):
    """Execute disconnect channel."""
    _verify_admin(x_admin_key)

    try:
        _update_channel_config(client_id, channel, {"connected": False})
        log_action(client_id, "channel", f"{channel}_disconnect",
                   client_id, {"channel": channel}, "success")

        return {"status": "disconnected", "channel": channel, "client_id": client_id}

    except Exception:
        raise HTTPException(status_code=500, detail="Disconnect failed")


def _update_channel_config(client_id: str, channel: str, data: dict):
    """Update channel config."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE clients
            SET channel_config = COALESCE(channel_config, '{}'::jsonb) || %s::jsonb
            WHERE client_id = %s
        """, (f'{{"{channel}": {__import__("json").dumps(data)}}}', client_id))
        cur.close()


def _verify_admin(key: Optional[str]):
    """Execute verify admin."""
    from config.settings import settings
    if not key or key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Unauthorised")