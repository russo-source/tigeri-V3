"""PayPal OAuth 2.0 (Identity Connect / Log In with PayPal).

Endpoints (sandbox):
- Authorize: https://www.sandbox.paypal.com/connect
- Token:     https://api-m.sandbox.paypal.com/v1/oauth2/token
- Identity:  https://api-m.sandbox.paypal.com/v1/identity/openidconnect/userinfo
- Payments:  https://api-m.sandbox.paypal.com/v2/payments

For Phase 1 demo we wire the OAuth round-trip + identity fetch only.
Real payment capture lands when the Procurement Agent ships in Phase 3.
"""

from __future__ import annotations

import base64
import secrets
import urllib.parse
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


AUTHORIZE_URL = "https://www.sandbox.paypal.com/connect"
TOKEN_URL = "https://api-m.sandbox.paypal.com/v1/oauth2/token"
USERINFO_URL = "https://api-m.sandbox.paypal.com/v1/identity/openidconnect/userinfo"

DEFAULT_SCOPES = "openid profile email"


def _redirect_uri() -> str:
    base = get_settings().public_api_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/callback/paypal"


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
        "flowEntry": "static",
        "client_id": client_id or settings.paypal_client_id,
        "response_type": "code",
        "scope": effective_scope,
        "redirect_uri": redirect_uri or _redirect_uri(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


def _basic_auth(client_id: str | None = None, client_secret: str | None = None) -> str:
    settings = get_settings()
    cid = client_id or settings.paypal_client_id
    csec = client_secret or settings.paypal_client_secret
    raw = f"{cid}:{csec}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def exchange_code(
    session: AsyncSession,
    *,
    tigeri_tenant_id: str,
    code: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,  # noqa: ARG001 — PayPal token endpoint doesn't need it
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
            },
        )
        resp.raise_for_status()
        token = resp.json()

        userinfo = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            params={"schema": "openid"},
        )
        userinfo.raise_for_status()
        u = userinfo.json()

    meta = {
        "paypal_email": u.get("email", ""),
        "paypal_name": u.get("name", ""),
        "scope": token.get("scope", DEFAULT_SCOPES),
    }
    await token_manager.save(
        session,
        tenant_id=tigeri_tenant_id,
        provider="paypal",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        expires_in_seconds=int(token.get("expires_in", 3600)),
        meta=meta,
    )
    return meta


async def _refresh_paypal(
    refresh_token: str,
    _meta: dict,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()
