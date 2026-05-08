"""Live per-provider health check.

For each provider the tenant has connected, exercise a cheap, read-only API
call to confirm the token still works (and refresh if the saved token is
near expiry). Returns a structured per-provider result the UI uses to render
green/yellow/red banners.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import google as google_int
from tigeri.integrations import microsoft as ms_int
from tigeri.integrations import paypal as paypal_int
from tigeri.integrations import quickbooks as qb_int
from tigeri.integrations import telegram as tg_int
from tigeri.integrations import tenant_creds
from tigeri.integrations import token_manager
from tigeri.integrations.xero import (
    CONNECTIONS_URL as XERO_CONNECTIONS_URL,
    _refresh_xero,
)


async def _byoa_refresh(
    session: AsyncSession, tenant_id: str, provider: str, refresh_fn
):
    """Wrap a provider's `_refresh_*` so it uses the tenant's BYOA client_id/
    client_secret when one is on file (falling back to platform creds otherwise).
    Without this the health check refresh would always send platform creds and
    401 against any tenant that connected via their own OAuth app."""

    try:
        creds = await tenant_creds.resolve(
            session, tenant_id=tenant_id, provider=provider
        )
    except ValueError:
        creds = None

    async def _wrapped(refresh_token: str, meta: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if creds is not None:
            kwargs["client_id"] = creds.client_id
            kwargs["client_secret"] = creds.client_secret
        return await refresh_fn(refresh_token, meta, **kwargs)

    return _wrapped


@dataclass
class ProviderHealth:
    provider: str
    connected: bool
    healthy: bool | None  # None when not connected
    latency_ms: int | None
    error: str | None
    meta: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "connected": self.connected,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "meta": self.meta,
        }


async def _measure(coro):
    import time

    start = time.perf_counter()
    try:
        await coro
        ms = int((time.perf_counter() - start) * 1000)
        return ms, None
    except httpx.HTTPStatusError as e:
        ms = int((time.perf_counter() - start) * 1000)
        return ms, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:  # noqa: BLE001
        ms = int((time.perf_counter() - start) * 1000)
        return ms, f"{type(e).__name__}: {str(e)[:200]}"


def _sandbox_health(provider: str, row) -> ProviderHealth | None:
    """Short-circuit for sandbox tokens — never hit the upstream API.

    Tokens written by the demo-connect endpoint carry ``meta.mode == "sandbox"``.
    They're always healthy by construction; the UI surfaces the sandbox tag.
    """
    meta = row.meta_json or {}
    if meta.get("mode") == "sandbox":
        return ProviderHealth(
            provider=provider,
            connected=True,
            healthy=True,
            latency_ms=0,
            error=None,
            meta=meta,
        )
    return None


async def _check_xero(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    row = await token_manager.get(session, tenant_id, "xero")
    if row is None:
        return ProviderHealth("xero", False, None, None, None, {})
    sandbox = _sandbox_health("xero", row)
    if sandbox is not None:
        return sandbox
    try:
        refresh = await _byoa_refresh(session, tenant_id, "xero", _refresh_xero)
        token = await token_manager.get_access_token(
            session, tenant_id, "xero", refresh_fn=refresh
        )
    except Exception as e:  # noqa: BLE001
        return ProviderHealth(
            "xero", True, False, None, f"refresh failed: {type(e).__name__}", row.meta_json or {}
        )

    async def call() -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                XERO_CONNECTIONS_URL,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()

    ms, err = await _measure(call())
    return ProviderHealth(
        "xero",
        True,
        err is None,
        ms,
        err,
        token.meta,
    )


async def _check_quickbooks(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    row = await token_manager.get(session, tenant_id, "quickbooks")
    if row is None:
        return ProviderHealth("quickbooks", False, None, None, None, {})
    sandbox = _sandbox_health("quickbooks", row)
    if sandbox is not None:
        return sandbox
    try:
        refresh = await _byoa_refresh(session, tenant_id, "quickbooks", qb_int._refresh_qb)
        token = await token_manager.get_access_token(
            session, tenant_id, "quickbooks", refresh_fn=refresh
        )
    except Exception as e:  # noqa: BLE001
        return ProviderHealth(
            "quickbooks", True, False, None, f"refresh failed: {type(e).__name__}", row.meta_json or {}
        )
    realm = token.meta.get("qb_realm_id", "")
    if not realm:
        return ProviderHealth(
            "quickbooks", True, False, None, "no realm id on file", token.meta
        )

    async def call() -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{qb_int.SANDBOX_API}/{realm}/companyinfo/{realm}",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/json",
                },
                params={"minorversion": "73"},
            )
            r.raise_for_status()

    ms, err = await _measure(call())
    return ProviderHealth("quickbooks", True, err is None, ms, err, token.meta)


async def _check_google(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    row = await token_manager.get(session, tenant_id, "google")
    if row is None:
        return ProviderHealth("google", False, None, None, None, {})
    sandbox = _sandbox_health("google", row)
    if sandbox is not None:
        return sandbox
    try:
        refresh = await _byoa_refresh(session, tenant_id, "google", google_int._refresh_google)
        token = await token_manager.get_access_token(
            session, tenant_id, "google", refresh_fn=refresh
        )
    except Exception as e:  # noqa: BLE001
        return ProviderHealth(
            "google", True, False, None, f"refresh failed: {type(e).__name__}", row.meta_json or {}
        )

    async def call() -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
            r.raise_for_status()

    ms, err = await _measure(call())
    return ProviderHealth("google", True, err is None, ms, err, token.meta)


async def _check_microsoft(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    row = await token_manager.get(session, tenant_id, "microsoft")
    if row is None:
        return ProviderHealth("microsoft", False, None, None, None, {})
    sandbox = _sandbox_health("microsoft", row)
    if sandbox is not None:
        return sandbox
    try:
        refresh = await _byoa_refresh(session, tenant_id, "microsoft", ms_int._refresh_microsoft)
        token = await token_manager.get_access_token(
            session, tenant_id, "microsoft", refresh_fn=refresh
        )
    except Exception as e:  # noqa: BLE001
        return ProviderHealth(
            "microsoft", True, False, None, f"refresh failed: {type(e).__name__}", row.meta_json or {}
        )

    async def call() -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{ms_int.GRAPH_BASE}/me",
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
            r.raise_for_status()

    ms, err = await _measure(call())
    return ProviderHealth("microsoft", True, err is None, ms, err, token.meta)


async def _check_paypal(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    row = await token_manager.get(session, tenant_id, "paypal")
    if row is None:
        return ProviderHealth("paypal", False, None, None, None, {})
    sandbox = _sandbox_health("paypal", row)
    if sandbox is not None:
        return sandbox
    try:
        refresh = await _byoa_refresh(session, tenant_id, "paypal", paypal_int._refresh_paypal)
        token = await token_manager.get_access_token(
            session, tenant_id, "paypal", refresh_fn=refresh
        )
    except Exception as e:  # noqa: BLE001
        return ProviderHealth(
            "paypal", True, False, None, f"refresh failed: {type(e).__name__}", row.meta_json or {}
        )

    async def call() -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                paypal_int.USERINFO_URL,
                headers={"Authorization": f"Bearer {token.access_token}"},
                params={"schema": "openid"},
            )
            r.raise_for_status()

    ms, err = await _measure(call())
    return ProviderHealth("paypal", True, err is None, ms, err, token.meta)


async def _check_telegram(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return ProviderHealth("telegram", False, None, None, "no bot token configured", {})
    chat_id = await tg_int.get_chat_id(session, tenant_id)
    meta: dict[str, Any] = {}
    row = await token_manager.get(session, tenant_id, "telegram")
    if row is not None:
        meta = dict(row.meta_json or {})

    async def call() -> None:
        await tg_int.get_me()

    ms, err = await _measure(call())
    healthy = err is None
    return ProviderHealth(
        "telegram",
        chat_id is not None,
        healthy if chat_id is not None else None,
        ms,
        err if not healthy else None,
        meta,
    )


async def _check_whatsapp(session: AsyncSession, tenant_id: str) -> ProviderHealth:
    from tigeri.integrations import whatsapp as wa_int

    settings = get_settings()
    if not settings.whatsapp_api_key:
        return ProviderHealth("whatsapp", False, None, None, "no api key configured", {})
    row = await token_manager.get(session, tenant_id, "whatsapp")
    meta: dict[str, Any] = {}
    has_recipient = False
    if row is not None:
        meta = dict(row.meta_json or {})
        has_recipient = bool(meta.get("recipient_msisdn"))
        sandbox = _sandbox_health("whatsapp", row)
        if sandbox is not None:
            return sandbox

    async def call() -> None:
        await wa_int.whoami()

    ms, err = await _measure(call())
    healthy = err is None
    return ProviderHealth(
        provider="whatsapp",
        connected=has_recipient,
        healthy=healthy if has_recipient else None,
        latency_ms=ms,
        error=err if not healthy else None,
        meta=meta,
    )


CHECKS = {
    "xero": _check_xero,
    "quickbooks": _check_quickbooks,
    "google": _check_google,
    "microsoft": _check_microsoft,
    "paypal": _check_paypal,
    "telegram": _check_telegram,
    "whatsapp": _check_whatsapp,
}


async def run_all(session: AsyncSession, tenant_id: str) -> list[ProviderHealth]:
    """Run every provider check sequentially. Errors per-provider don't fail
    the overall response — each ProviderHealth captures its own outcome."""

    results: list[ProviderHealth] = []
    for name, fn in CHECKS.items():
        try:
            results.append(await fn(session, tenant_id))
        except Exception as e:  # noqa: BLE001
            results.append(
                ProviderHealth(
                    provider=name,
                    connected=False,
                    healthy=False,
                    latency_ms=None,
                    error=f"{type(e).__name__}: {str(e)[:200]}",
                    meta={},
                )
            )
    return results
