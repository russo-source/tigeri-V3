"""WhatsApp Business client via 360dialog (BSP).

360dialog wraps the Meta WhatsApp Business API. Auth is a single static
``D360-API-KEY`` header — no OAuth dance per tenant.

Endpoints:
- Sandbox: ``https://waba-sandbox.360dialog.io/v1``
- Production: ``https://waba.360dialog.io/v1``

Per-tenant ``recipient_msisdn`` is stored in ``tenant_integrations.meta_json``
once the operator opts in their phone via the /integrations/whatsapp/optin
endpoint (or by sending a free-form message to the bot number).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


def _base_url() -> str:
    settings = get_settings()
    return (
        "https://waba-sandbox.360dialog.io/v1"
        if settings.whatsapp_use_sandbox
        else "https://waba.360dialog.io/v1"
    )


def _headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.whatsapp_api_key:
        raise RuntimeError("WHATSAPP_API_KEY is not set")
    return {
        "D360-API-KEY": settings.whatsapp_api_key,
        "Content-Type": "application/json",
    }


@dataclass
class WhatsAppText:
    to_msisdn: str  # E.164 without leading + (e.g. 9995322303 or 919995322303)
    text: str


async def send_text(msg: WhatsAppText) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": msg.to_msisdn,
        "type": "text",
        "text": {"body": msg.text},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_base_url()}/messages", headers=_headers(), json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp 360dialog send {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()


# ---- Per-tenant opt-in (recipient phone number storage) ----------------


async def remember_optin(
    session: AsyncSession,
    *,
    tenant_id: str,
    recipient_msisdn: str,
    note: str = "",
) -> None:
    meta = {
        "recipient_msisdn": recipient_msisdn,
        "opted_in_at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    row = await token_manager.get(session, tenant_id, "whatsapp")
    if row is None:
        await token_manager.save(
            session,
            tenant_id=tenant_id,
            provider="whatsapp",
            access_token="d360-api-key-from-env",  # auth is in env, not per-tenant
            refresh_token="",
            expires_in_seconds=10**9,
            meta=meta,
        )
    else:
        row.meta_json = {**(row.meta_json or {}), **meta}
        row.updated_at = datetime.now(UTC)


async def get_recipient(session: AsyncSession, tenant_id: str) -> str | None:
    row = await token_manager.get(session, tenant_id, "whatsapp")
    if row is None:
        return None
    return (row.meta_json or {}).get("recipient_msisdn")


# ---- Health probe (used by integrations/health.py) ---------------------


async def whoami() -> dict[str, Any]:
    """Hit a cheap 360dialog endpoint to confirm the API key works.

    ``/v1/configs/webhook`` returns the bot's webhook config and is available
    on both sandbox and prod. A 200 (with or without a configured webhook)
    proves the API key is recognised.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(f"{_base_url()}/configs/webhook", headers=_headers())
        # 404 with body {"detail":"Not Found"} means no webhook configured
        # yet — but the key itself is valid; treat that as healthy.
        if resp.status_code == 404:
            return {"status": "ok", "webhook_configured": False}
        if resp.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp 360dialog whoami {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return {"status": "ok", "raw_len": len(resp.text)}
        return {"status": "ok", "webhook_configured": True, "config": data}
