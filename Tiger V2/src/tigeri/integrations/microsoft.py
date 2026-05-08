"""Microsoft 365 OAuth 2.0 + Graph API client.

Endpoints (multi-tenant common endpoint):
- Authorize: https://login.microsoftonline.com/common/oauth2/v2.0/authorize
- Token:     https://login.microsoftonline.com/common/oauth2/v2.0/token
- Graph:     https://graph.microsoft.com/v1.0

Scopes: Outlook send + Teams chat + offline_access for refresh tokens.
"""

from __future__ import annotations

import secrets
import urllib.parse
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

DEFAULT_SCOPES = " ".join(
    [
        "openid",
        "profile",
        "email",
        "offline_access",
        "User.Read",
        "Mail.Send",
        "Calendars.ReadWrite",
    ]
)


def _redirect_uri() -> str:
    base = get_settings().public_api_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/callback/microsoft"


def authorize_url(
    tenant_id: str,
    *,
    state: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> tuple[str, str]:
    """Build the OAuth authorize URL. BYOA-aware."""
    settings = get_settings()
    if state is None:
        state = f"{tenant_id}:{secrets.token_urlsafe(24)}"
    effective_scope = " ".join(scopes) if scopes else DEFAULT_SCOPES
    params = {
        "client_id": client_id or settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri or _redirect_uri(),
        "scope": effective_scope,
        "response_mode": "query",
        "state": state,
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


async def exchange_code(
    session: AsyncSession,
    *,
    tigeri_tenant_id: str,
    code: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    cid = client_id or settings.microsoft_client_id
    csec = client_secret or settings.microsoft_client_secret_value
    redir = redirect_uri or _redirect_uri()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "code": code,
                "redirect_uri": redir,
                "grant_type": "authorization_code",
                "scope": DEFAULT_SCOPES,
            },
        )
        resp.raise_for_status()
        token = resp.json()

        # /me to capture identity for the UI
        me = await client.get(
            f"{GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        me.raise_for_status()
        me_json = me.json()

    meta = {
        "ms_user": me_json.get("userPrincipalName", ""),
        "ms_display_name": me_json.get("displayName", ""),
        "scope": token.get("scope", DEFAULT_SCOPES),
    }
    await token_manager.save(
        session,
        tenant_id=tigeri_tenant_id,
        provider="microsoft",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        expires_in_seconds=int(token.get("expires_in", 3600)),
        meta=meta,
    )
    return meta


async def _refresh_microsoft(
    refresh_token: str,
    _meta: dict,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id or settings.microsoft_client_id,
                "client_secret": client_secret or settings.microsoft_client_secret_value,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": DEFAULT_SCOPES,
            },
        )
        resp.raise_for_status()
        return resp.json()


class MicrosoftClient:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    @classmethod
    async def for_tenant(cls, session: AsyncSession, tigeri_tenant_id: str) -> "MicrosoftClient":
        from tigeri.integrations import tenant_creds

        creds = await tenant_creds.resolve(
            session, tenant_id=tigeri_tenant_id, provider="microsoft"
        )

        async def _refresh(refresh_token: str, meta: dict) -> dict[str, Any]:
            return await _refresh_microsoft(
                refresh_token,
                meta,
                client_id=creds.client_id,
                client_secret=creds.client_secret,
            )

        token = await token_manager.get_access_token(
            session, tigeri_tenant_id, "microsoft", refresh_fn=_refresh
        )
        return cls(access_token=token.access_token)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def send_mail(self, to: str, subject: str, body: str) -> None:
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": "true",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/sendMail", headers=self._headers, json=payload
            )
            resp.raise_for_status()
