"""QuickBooks Online OAuth 2.0 + invoice posting.

Endpoints:
- Authorize:  https://appcenter.intuit.com/connect/oauth2
- Token:      https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
- Sandbox API base: https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}
- Production API base: https://quickbooks.api.intuit.com/v3/company/{realmId}

The realm id arrives as a query param on the callback (``realmId``).
"""

from __future__ import annotations

import base64
import secrets
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SANDBOX_API = "https://sandbox-quickbooks.api.intuit.com/v3/company"

DEFAULT_SCOPES = "com.intuit.quickbooks.accounting openid profile email"


def _redirect_uri() -> str:
    base = get_settings().public_api_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/callback/quickbooks"


def authorize_url(
    tenant_id: str,
    *,
    state: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> tuple[str, str]:
    """Build the OAuth authorize URL.

    ``client_id``/``redirect_uri``/``scopes`` override the platform defaults
    so a tenant's BYOA registration applies (resolved via
    :mod:`tigeri.integrations.tenant_creds`). ``state`` is a CSRF nonce
    issued by :func:`tigeri.integrations.oauth_state.issue`.
    """
    settings = get_settings()
    if state is None:
        state = f"{tenant_id}:{secrets.token_urlsafe(24)}"
    effective_scope = " ".join(scopes) if scopes else DEFAULT_SCOPES
    params = {
        "client_id": client_id or settings.quickbooks_client_id,
        "response_type": "code",
        "scope": effective_scope,
        "redirect_uri": redirect_uri or _redirect_uri(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


def _basic_auth(client_id: str | None = None, client_secret: str | None = None) -> str:
    settings = get_settings()
    cid = client_id or settings.quickbooks_client_id
    csec = client_secret or settings.quickbooks_client_secret
    raw = f"{cid}:{csec}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def exchange_code(
    session: AsyncSession,
    *,
    tigeri_tenant_id: str,
    code: str,
    realm_id: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri or _redirect_uri(),
            },
        )
        resp.raise_for_status()
        token = resp.json()

    meta = {
        "qb_realm_id": realm_id,
        "qb_environment": "sandbox",
        "scope": token.get("scope", DEFAULT_SCOPES),
    }
    await token_manager.save(
        session,
        tenant_id=tigeri_tenant_id,
        provider="quickbooks",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        expires_in_seconds=int(token.get("expires_in", 3600)),
        meta=meta,
    )
    return meta


async def _refresh_qb(
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
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()


# ---- Client -------------------------------------------------------------


@dataclass
class QBInvoiceRequest:
    customer_name: str
    line_description: str
    amount: Decimal
    invoice_number: str


class QuickBooksClient:
    def __init__(self, access_token: str, realm_id: str) -> None:
        self._access_token = access_token
        self._realm_id = realm_id

    @classmethod
    async def for_tenant(cls, session: AsyncSession, tigeri_tenant_id: str) -> "QuickBooksClient":
        from tigeri.integrations import tenant_creds

        creds = await tenant_creds.resolve(
            session, tenant_id=tigeri_tenant_id, provider="quickbooks"
        )

        async def _refresh(refresh_token: str, meta: dict) -> dict[str, Any]:
            return await _refresh_qb(
                refresh_token,
                meta,
                client_id=creds.client_id,
                client_secret=creds.client_secret,
            )

        token = await token_manager.get_access_token(
            session, tigeri_tenant_id, "quickbooks", refresh_fn=_refresh
        )
        realm = token.meta.get("qb_realm_id", "")
        if not realm:
            raise RuntimeError(
                f"QuickBooks connection for {tigeri_tenant_id} has no realm id; reconnect."
            )
        return cls(access_token=token.access_token, realm_id=realm)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def post_invoice(self, req: QBInvoiceRequest) -> dict[str, Any]:
        # Minimal QB invoice — uses default item/income account "1" (sandbox seed)
        payload = {
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": float(req.amount),
                    "Description": req.line_description,
                    "SalesItemLineDetail": {"ItemRef": {"value": "1"}},
                }
            ],
            "CustomerRef": {"name": req.customer_name, "value": "1"},
            "DocNumber": req.invoice_number[:20],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{SANDBOX_API}/{self._realm_id}/invoice",
                headers=self._headers,
                json=payload,
                params={"minorversion": "73"},
            )
            resp.raise_for_status()
            return resp.json()
