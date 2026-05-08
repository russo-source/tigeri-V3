"""Telegram Bot API client.

Telegram bots authenticate with a single fixed token (not OAuth). For outbound
notifications we just POST to ``api.telegram.org/bot<TOKEN>/sendMessage``.
For inbound, Telegram pushes updates to a webhook URL that we register once
via ``setWebhook``.

Per-tenant ``chat_id`` is stored in ``tenant_integrations.meta_json`` once
the tenant has chatted with the bot at least once and we've recorded the
chat from the webhook.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


API_BASE = "https://api.telegram.org"


def _bot_url(method: str) -> str:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return f"{API_BASE}/bot{settings.telegram_bot_token}/{method}"


@dataclass
class TelegramMessage:
    chat_id: int | str
    text: str
    parse_mode: str | None = None  # None = plain text, no special-char escaping


async def send_message(msg: TelegramMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": msg.chat_id,
        "text": msg.text,
        "disable_web_page_preview": True,
    }
    if msg.parse_mode:
        payload["parse_mode"] = msg.parse_mode
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_bot_url("sendMessage"), json=payload)
        if resp.status_code >= 400:
            # Surface Telegram's actual error so logs are useful
            raise RuntimeError(
                f"Telegram sendMessage {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()


async def set_webhook(public_webhook_url: str, secret_token: str) -> dict[str, Any]:
    """Register the webhook with Telegram. Idempotent — call any time the URL changes."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("setWebhook"),
            json={
                "url": public_webhook_url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_me() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_bot_url("getMe"))
        resp.raise_for_status()
        return resp.json()


# ---- Per-tenant chat-id storage -----------------------------------------


async def remember_chat(
    session: AsyncSession, tenant_id: str, chat_id: int, sender: dict[str, Any]
) -> None:
    """Record (or update) the chat_id this tenant uses for Telegram comms."""
    row = await token_manager.get(session, tenant_id, "telegram")
    meta = {
        "chat_id": chat_id,
        "first_name": sender.get("first_name", ""),
        "username": sender.get("username", ""),
        "last_seen_utc": datetime.now(UTC).isoformat(),
    }
    if row is None:
        # Telegram has no OAuth tokens; we re-use the table for chat_id storage.
        await token_manager.save(
            session,
            tenant_id=tenant_id,
            provider="telegram",
            access_token="bot-token-from-env",  # dummy; real token is in env
            refresh_token="",
            expires_in_seconds=10**9,  # effectively never expires
            meta=meta,
        )
    else:
        row.meta_json = {**(row.meta_json or {}), **meta}
        row.updated_at = datetime.now(UTC)


async def get_chat_id(session: AsyncSession, tenant_id: str) -> int | None:
    row = await token_manager.get(session, tenant_id, "telegram")
    if row is None:
        return None
    chat_id = (row.meta_json or {}).get("chat_id")
    return int(chat_id) if chat_id is not None else None


async def find_tenant_for_chat(session: AsyncSession, chat_id: int) -> str | None:
    """Reverse lookup: which tenant did this Telegram chat link to?

    Used by the inbound webhook to route a free-form chat message into the
    orchestrator under the right tenant context.
    """
    from sqlalchemy import select

    from tigeri.integrations.models import TenantIntegration

    result = await session.execute(
        select(TenantIntegration).where(TenantIntegration.provider == "telegram")
    )
    for row in result.scalars():
        meta = row.meta_json or {}
        if int(meta.get("chat_id", 0) or 0) == int(chat_id):
            return row.tenant_id
    return None


def escape_markdown(text: str) -> str:
    """Telegram MarkdownV2 escapes — required for safe text rendering."""
    chars = "_*[]()~`>#+-=|{}.!\\"
    return "".join(("\\" + c) if c in chars else c for c in text)
