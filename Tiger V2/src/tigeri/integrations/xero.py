"""Xero OAuth 2.0 client + invoice posting.

Auth flow (Xero Standard OAuth 2.0 + PKCE not used here — confidential client):

1. Frontend → ``GET /api/v1/integrations/connect/xero`` → 302 to Xero authorize URL
2. User logs in to Xero, picks a tenant, consents
3. Xero → 302 ``GET /api/v1/integrations/callback/xero?code=...&state=...``
4. Backend exchanges code for tokens, calls ``/connections`` to discover the
   Xero tenant id, persists encrypted tokens via token_manager
5. Subsequent agent calls use ``XeroClient(tenant_id).post_invoice(...)`` which
   transparently refreshes the token when needed

Reference URLs:
- Authorize: https://login.xero.com/identity/connect/authorize
- Token:     https://identity.xero.com/connect/token
- API:       https://api.xero.com/api.xro/2.0
- Connections: https://api.xero.com/connections
"""

from __future__ import annotations

import base64
import os
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
API_BASE = "https://api.xero.com/api.xro/2.0"
CONNECTIONS_URL = "https://api.xero.com/connections"

# Apps created after 2 March 2026 use granular scopes; older apps use broad scopes.
# Override via XERO_SCOPES env var. Default is the minimum auth scopes that work
# for any app type — add accounting.* scopes once you confirm OAuth works end-to-end.
DEFAULT_SCOPES = os.getenv(
    "XERO_SCOPES",
    "openid profile email offline_access",
)


def authorize_url(
    tenant_id: str,
    *,
    state: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> tuple[str, str]:
    """Return (authorize_url, state). BYOA-aware."""
    settings = get_settings()
    if state is None:
        state = f"{tenant_id}:{secrets.token_urlsafe(24)}"
    effective_scope = " ".join(scopes) if scopes else DEFAULT_SCOPES
    params = {
        "response_type": "code",
        "client_id": client_id or settings.xero_client_id,
        "redirect_uri": redirect_uri or _redirect_uri(),
        "scope": effective_scope,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


def _redirect_uri() -> str:
    """Derive the Xero callback URL from settings.

    Xero requires HTTPS unless the URL is localhost. ``TIGERI_PUBLIC_API_BASE_URL``
    must be the public scheme+host the user's browser hits.
    """
    base = get_settings().public_api_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/callback/xero"


def _basic_auth_header(client_id: str | None = None, client_secret: str | None = None) -> str:
    settings = get_settings()
    cid = client_id or settings.xero_client_id
    csec = client_secret or settings.xero_client_secret
    raw = f"{cid}:{csec}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def exchange_code(
    session: AsyncSession,
    *,
    tigeri_tenant_id: str,
    code: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    """Step 4: exchange the auth code for tokens, discover the Xero tenant,
    persist encrypted credentials. Returns the picked Xero tenant info.

    BYOA: when client_id/secret are passed they override the platform env
    defaults, so each customer can plug in their own Xero app registration.
    """

    redir = redirect_uri or _redirect_uri()
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": _basic_auth_header(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redir,
            },
        )
        token_resp.raise_for_status()
        token = token_resp.json()

        # Discover Xero tenants this token has access to
        conns_resp = await client.get(
            CONNECTIONS_URL,
            headers={
                "Authorization": f"Bearer {token['access_token']}",
                "Accept": "application/json",
            },
        )
        conns_resp.raise_for_status()
        conns = conns_resp.json()

    # Pick the first tenant returned by /connections. If empty (some Xero
    # apps return [] until first API call), fall back to the configured
    # XERO_TENANT_ID from env.
    xero_tenant = conns[0] if conns else {}
    fallback_tenant = get_settings().xero_tenant_id
    meta = {
        "xero_tenant_id": xero_tenant.get("tenantId") or fallback_tenant or "",
        "xero_tenant_name": xero_tenant.get("tenantName", ""),
        "scope": token.get("scope", DEFAULT_SCOPES),
    }
    await token_manager.save(
        session,
        tenant_id=tigeri_tenant_id,
        provider="xero",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        expires_in_seconds=int(token.get("expires_in", 1800)),
        meta=meta,
    )
    return meta


async def _refresh_xero(
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
                "Authorization": _basic_auth_header(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()


# ---- Client ---------------------------------------------------------------


@dataclass
class XeroInvoiceRequest:
    contact_name: str
    line_description: str
    amount: Decimal
    currency: str
    invoice_number: str
    due_date: str | None = None  # ISO date
    # Tax handling — when ``tax_total > 0`` we render tax as a separate line
    # so we don't depend on org-specific tax codes.
    tax_total: Decimal = Decimal("0")
    tax_rate_label: str = ""  # human label for the tax line, e.g. "GST 10%"


@dataclass
class XeroInvoiceResult:
    xero_invoice_id: str
    invoice_number: str
    status: str
    contact_name: str
    view_url: str = ""  # Deep link into the Xero web UI


class XeroClient:
    """Async wrapper. Construct per-call: ``await XeroClient.for_tenant(session, 'tnt_x').post_invoice(...)``."""

    def __init__(self, access_token: str, xero_tenant_id: str) -> None:
        self._access_token = access_token
        self._xero_tenant_id = xero_tenant_id

    @classmethod
    async def for_tenant(cls, session: AsyncSession, tigeri_tenant_id: str) -> "XeroClient":
        from tigeri.integrations import tenant_creds

        creds = await tenant_creds.resolve(
            session, tenant_id=tigeri_tenant_id, provider="xero"
        )

        async def _refresh(refresh_token: str, meta: dict) -> dict[str, Any]:
            return await _refresh_xero(
                refresh_token,
                meta,
                client_id=creds.client_id,
                client_secret=creds.client_secret,
            )

        token = await token_manager.get_access_token(
            session, tigeri_tenant_id, "xero", refresh_fn=_refresh
        )
        xero_tenant = token.meta.get("xero_tenant_id", "")
        if not xero_tenant:
            raise RuntimeError(
                f"Xero connection for {tigeri_tenant_id} has no xero_tenant_id; reconnect."
            )
        return cls(access_token=token.access_token, xero_tenant_id=xero_tenant)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Xero-tenant-id": self._xero_tenant_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def fetch_invoice_pdf(self, xero_invoice_id: str) -> bytes:
        """Pull the rendered PDF for an invoice this Xero org can see.

        Streams the file end-to-end as bytes — caller is responsible for
        sending it back to the browser (e.g. via FastAPI StreamingResponse).
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{API_BASE}/Invoices/{xero_invoice_id}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Xero-tenant-id": self._xero_tenant_id,
                    "Accept": "application/pdf",
                },
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Xero PDF fetch {resp.status_code}: {resp.text[:300]}"
                )
            return resp.content

    async def post_invoice(self, req: XeroInvoiceRequest) -> XeroInvoiceResult:
        due = req.due_date or (date.today() + timedelta(days=30)).isoformat()

        line_items = [
            {
                "Description": req.line_description,
                "Quantity": 1.0,
                "UnitAmount": float(req.amount),
                "AccountCode": "200",  # default Sales account
            }
        ]
        if req.tax_total > 0:
            tax_desc = "Tax"
            if req.tax_rate_label:
                tax_desc = f"Tax — {req.tax_rate_label}"
            line_items.append(
                {
                    "Description": tax_desc,
                    "Quantity": 1.0,
                    "UnitAmount": float(req.tax_total),
                    "AccountCode": "200",
                }
            )

        payload = {
            "Invoices": [
                {
                    "Type": "ACCREC",
                    "Contact": {"Name": req.contact_name},
                    "LineItems": line_items,
                    "Date": date.today().isoformat(),
                    "DueDate": due,
                    "Reference": req.invoice_number,
                    "CurrencyCode": req.currency.upper(),
                    "Status": "DRAFT",
                    "LineAmountTypes": "NoTax",
                }
            ]
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API_BASE}/Invoices", headers=self._headers, json=payload
            )
            if resp.status_code >= 400:
                # Extract just the ValidationErrors array — that's where Xero
                # tells us *what* was wrong (missing field / bad code / etc.)
                try:
                    body = resp.json()
                    elements = body.get("Elements") or []
                    msgs: list[str] = []
                    for el in elements:
                        for ve in el.get("ValidationErrors") or []:
                            msgs.append(ve.get("Message", ""))
                        for li in el.get("LineItems") or []:
                            for ve in li.get("ValidationErrors") or []:
                                msgs.append(f"line: {ve.get('Message', '')}")
                    detail = " | ".join(m for m in msgs if m) or resp.text[:1500]
                except Exception:  # noqa: BLE001
                    detail = resp.text[:1500]
                raise RuntimeError(
                    f"Xero invoice POST {resp.status_code}: {detail}"
                )
            data = resp.json()
        inv = data["Invoices"][0]
        invoice_id = inv["InvoiceID"]
        return XeroInvoiceResult(
            xero_invoice_id=invoice_id,
            invoice_number=inv.get("InvoiceNumber", req.invoice_number),
            status=inv.get("Status", "DRAFT"),
            contact_name=inv["Contact"]["Name"],
            view_url=f"https://go.xero.com/app/invoicing/edit/{invoice_id}",
        )
