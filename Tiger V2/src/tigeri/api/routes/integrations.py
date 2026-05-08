"""Integration routes — OAuth connect/callback for each provider, plus Telegram webhook."""

import re

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.api.deps import get_session, get_tenant_id
from tigeri.auth.admin import require_admin
from tigeri.auth.scope import TenantScope, get_scope
from tigeri.core.config import get_settings
from tigeri.core.logging import get_logger
from tigeri.integrations import google as google_int
from tigeri.integrations import microsoft as ms_int
from tigeri.integrations import oauth_state
from tigeri.integrations import paypal as paypal_int
from tigeri.integrations import tenant_creds
from tigeri.integrations import quickbooks as qb_int
from tigeri.integrations import telegram as tg_int
from tigeri.integrations import telegram_link
from tigeri.integrations import token_manager
from tigeri.integrations import whatsapp as wa_int
from tigeri.integrations.xero import authorize_url as xero_authorize_url
from tigeri.integrations.xero import exchange_code as xero_exchange_code

logger = get_logger(__name__)

# nginx strips the public ``/api/`` prefix before forwarding to uvicorn, so the
# router exposes ``/v1/integrations/...`` here. Externally OAuth providers hit
# ``https://<host>/api/v1/integrations/callback/...`` which lands at this path.
router = APIRouter(prefix="/v1/integrations", tags=["integrations"])


def _resolve_tenant(query_tenant: str | None, header_tenant: str | None) -> str:
    tid = header_tenant or query_tenant
    if not tid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "tenant_id required (X-Tigeri-Tenant-Id header or ?tenant_id= query)",
        )
    return tid


def _success_redirect(provider: str, meta: dict | None = None) -> str:
    frontend = get_settings().frontend_base_url.rstrip("/")
    extras = ""
    if meta:
        for k, v in meta.items():
            if isinstance(v, str) and v:
                extras += f"&{k}={v}"
    return f"{frontend}/integrations?integration={provider}&status=connected{extras}"


def _failure_redirect(provider: str, reason: str) -> str:
    frontend = get_settings().frontend_base_url.rstrip("/")
    return f"{frontend}/integrations?integration={provider}&status=failed&reason={reason}"


def _check_callback_params(
    provider: str, code: str | None, state: str | None, error: str | None
) -> RedirectResponse | None:
    """Common guard at the top of every OAuth callback.

    Three cases the provider's redirect can land us in:
    - User clicked Deny / Google rejected the request → ``?error=access_denied``
    - User typed the URL directly with no query params at all → all None
    - Happy path → both code + state present, return None and let the
      caller exchange the code for a token.

    Without this guard, FastAPI's Query(...) raises a 422 for case 2 with
    a raw JSON validation error — confusing for anyone who pastes the
    callback URL by mistake. We instead bounce to the integrations page
    with a clear ``status=failed&reason=...`` so the UI can show a
    friendly message."""

    if error:
        return RedirectResponse(_failure_redirect(provider, error), 302)
    if not code or not state:
        return RedirectResponse(
            _failure_redirect(provider, "callback_hit_directly"), 302
        )
    return None


# ---- /status -------------------------------------------------------------


@router.get("/health")
async def health_check(
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Live per-provider check — exercises a cheap API call against each
    connected provider's token. Any authenticated user can read this so the
    frontend can show health badges; mutating the integrations themselves is
    admin-only (see PUT/DELETE handlers below)."""
    from tigeri.integrations.health import run_all

    results = [r.as_dict() for r in await run_all(session, scope.tenant_id)]
    summary = {
        "connected": sum(1 for r in results if r["connected"]),
        "healthy": sum(1 for r in results if r["healthy"] is True),
        "failing": sum(1 for r in results if r["healthy"] is False),
        "total": len(results),
    }
    return {"summary": summary, "providers": results}


@router.get("/status")
async def status_all(
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    out: dict[str, dict] = {}
    for provider in ("xero", "quickbooks", "google", "microsoft", "paypal", "telegram", "whatsapp"):
        row = await token_manager.get(session, scope.tenant_id, provider)
        if row is None:
            out[provider] = {"connected": False}
        else:
            out[provider] = {
                "connected": True,
                "expires_at": row.access_token_expires_at.isoformat(),
                "is_expired": row.is_expired,
                "meta": {
                    k: str(v)
                    for k, v in (row.meta_json or {}).items()
                    if not k.endswith("_secret") and not k.endswith("_token")
                },
            }
    return out


# ---- Generic OAuth connect per provider ---------------------------------


@router.get("/connect/{provider}")
async def connect_provider(
    provider: str,
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Initiate the OAuth connect flow. Admin role required — connecting an
    external system to a tenant is an org-wide action, not a member-level one."""
    effective = scope.tenant_id
    settings = get_settings()

    valid_providers = {"xero", "quickbooks", "google", "microsoft", "paypal"}
    if provider not in valid_providers:
        raise HTTPException(404, f"unknown provider {provider}")

    # Issue a fresh CSRF nonce, persist (nonce, tenant_id, provider, user_id)
    # before redirecting. The callback verifies the nonce + recovers the
    # tenant from the row — never from the URL.
    nonce = await oauth_state.issue(
        session,
        tenant_id=effective,
        provider=provider,
        user_id=scope.user_id,
    )

    # Resolve effective OAuth creds — tenant's BYOA registration if configured,
    # else platform default. Raises if neither is set.
    try:
        creds = await tenant_creds.resolve(session, tenant_id=effective, provider=provider)
    except ValueError as e:
        raise HTTPException(412, str(e)) from e

    kwargs = {
        "state": nonce,
        "client_id": creds.client_id,
        "redirect_uri": creds.redirect_uri,
        "scopes": creds.scopes,
    }
    if provider == "xero":
        url, _ = xero_authorize_url(effective, **kwargs)
    elif provider == "quickbooks":
        url, _ = qb_int.authorize_url(effective, **kwargs)
    elif provider == "google":
        url, _ = google_int.authorize_url(effective, **kwargs)
    elif provider == "microsoft":
        url, _ = ms_int.authorize_url(effective, **kwargs)
    elif provider == "paypal":
        url, _ = paypal_int.authorize_url(effective, **kwargs)

    return RedirectResponse(url=url, status_code=302)


# ---- Callbacks (one per provider) --------------------------------------


@router.get("/callback/xero")
async def callback_xero(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if (early := _check_callback_params("xero", code, state, error)) is not None:
        return early
    try:
        tigeri_tenant_id = await oauth_state.consume(
            session, state_nonce=state, provider="xero"
        )
    except oauth_state.InvalidStateError as e:
        logger.warning("xero callback rejected: %s", e)
        return RedirectResponse(_failure_redirect("xero", "csrf_check_failed"), 302)
    creds = await tenant_creds.resolve(
        session, tenant_id=tigeri_tenant_id, provider="xero"
    )
    try:
        meta = await xero_exchange_code(
            session,
            tigeri_tenant_id=tigeri_tenant_id,
            code=code,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("xero callback failed")
        return RedirectResponse(_failure_redirect("xero", type(e).__name__), 302)
    return RedirectResponse(
        _success_redirect("xero", {"xero_tenant": meta.get("xero_tenant_name", "")}), 302
    )


@router.get("/callback/quickbooks")
async def callback_quickbooks(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    realmId: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if (early := _check_callback_params("quickbooks", code, state, error)) is not None:
        return early
    if not realmId:
        return RedirectResponse(_failure_redirect("quickbooks", "missing_realm_id"), 302)
    try:
        tigeri_tenant_id = await oauth_state.consume(
            session, state_nonce=state, provider="quickbooks"
        )
    except oauth_state.InvalidStateError as e:
        logger.warning("quickbooks callback rejected: %s", e)
        return RedirectResponse(_failure_redirect("quickbooks", "csrf_check_failed"), 302)
    creds = await tenant_creds.resolve(
        session, tenant_id=tigeri_tenant_id, provider="quickbooks"
    )
    try:
        meta = await qb_int.exchange_code(
            session,
            tigeri_tenant_id=tigeri_tenant_id,
            code=code,
            realm_id=realmId,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("quickbooks callback failed")
        return RedirectResponse(_failure_redirect("quickbooks", type(e).__name__), 302)
    return RedirectResponse(
        _success_redirect("quickbooks", {"qb_realm": meta.get("qb_realm_id", "")}), 302
    )


@router.get("/callback/google")
async def callback_google(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if (early := _check_callback_params("google", code, state, error)) is not None:
        return early
    try:
        tigeri_tenant_id = await oauth_state.consume(
            session, state_nonce=state, provider="google"
        )
    except oauth_state.InvalidStateError as e:
        logger.warning("google callback rejected: %s", e)
        return RedirectResponse(_failure_redirect("google", "csrf_check_failed"), 302)
    creds = await tenant_creds.resolve(
        session, tenant_id=tigeri_tenant_id, provider="google"
    )
    try:
        meta = await google_int.exchange_code(
            session,
            tigeri_tenant_id=tigeri_tenant_id,
            code=code,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("google callback failed")
        return RedirectResponse(_failure_redirect("google", type(e).__name__), 302)
    return RedirectResponse(
        _success_redirect("google", {"google_email": meta.get("google_email", "")}), 302
    )


@router.get("/callback/microsoft")
async def callback_microsoft(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if (early := _check_callback_params("microsoft", code, state, error)) is not None:
        return early
    try:
        tigeri_tenant_id = await oauth_state.consume(
            session, state_nonce=state, provider="microsoft"
        )
    except oauth_state.InvalidStateError as e:
        logger.warning("microsoft callback rejected: %s", e)
        return RedirectResponse(_failure_redirect("microsoft", "csrf_check_failed"), 302)
    creds = await tenant_creds.resolve(
        session, tenant_id=tigeri_tenant_id, provider="microsoft"
    )
    try:
        meta = await ms_int.exchange_code(
            session,
            tigeri_tenant_id=tigeri_tenant_id,
            code=code,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("microsoft callback failed")
        return RedirectResponse(_failure_redirect("microsoft", type(e).__name__), 302)
    return RedirectResponse(
        _success_redirect("microsoft", {"ms_user": meta.get("ms_user", "")}), 302
    )


@router.get("/callback/paypal")
async def callback_paypal(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if (early := _check_callback_params("paypal", code, state, error)) is not None:
        return early
    try:
        tigeri_tenant_id = await oauth_state.consume(
            session, state_nonce=state, provider="paypal"
        )
    except oauth_state.InvalidStateError as e:
        logger.warning("paypal callback rejected: %s", e)
        return RedirectResponse(_failure_redirect("paypal", "csrf_check_failed"), 302)
    creds = await tenant_creds.resolve(
        session, tenant_id=tigeri_tenant_id, provider="paypal"
    )
    try:
        meta = await paypal_int.exchange_code(
            session,
            tigeri_tenant_id=tigeri_tenant_id,
            code=code,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("paypal callback failed")
        return RedirectResponse(_failure_redirect("paypal", type(e).__name__), 302)
    return RedirectResponse(
        _success_redirect("paypal", {"paypal_email": meta.get("paypal_email", "")}), 302
    )


# ---- Demo connect (sandbox mode) --------------------------------------

_DEMO_PROVIDERS = {"xero", "quickbooks", "google", "microsoft", "paypal"}


@router.post("/connect-demo/{provider}")
async def connect_demo(
    provider: str,
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark a provider as 'connected (demo)' — inserts a sandbox token row so
    health checks pass and the agents post via the safe stub but tag every
    side-effect with the provider name (e.g. ``xero_sandbox:<id>``).

    Admin role required — demo-connecting fakes an integration for the whole
    tenant; not a member-level action."""

    tenant_id = scope.tenant_id
    if provider not in _DEMO_PROVIDERS:
        raise HTTPException(404, f"unknown provider {provider}")
    meta = {
        "mode": "sandbox",
        "demo_label": f"{provider}_sandbox",
        "note": "demo-connected (no real OAuth)",
    }
    if provider == "xero":
        meta["xero_tenant_id"] = "sandbox-tenant"
        meta["xero_tenant_name"] = "Sandbox Org"
    elif provider == "quickbooks":
        meta["qb_realm_id"] = "sandbox-realm"
    elif provider == "google":
        meta["google_email"] = "sandbox@tigeri.demo"
    elif provider == "microsoft":
        meta["ms_user"] = "sandbox@tigeri.demo"
    elif provider == "paypal":
        meta["paypal_email"] = "sandbox@tigeri.demo"

    await token_manager.save(
        session,
        tenant_id=tenant_id,
        provider=provider,
        access_token="sandbox-access-token",
        refresh_token="sandbox-refresh-token",
        expires_in_seconds=10**9,
        meta=meta,
    )
    await session.commit()
    return {"connected": True, "mode": "sandbox", "provider": provider, "meta": meta}


# ---- Disconnect any provider -------------------------------------------


@router.delete("/{provider}")
async def disconnect(
    provider: str,
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Disconnect an integration. Admin role required — revokes every agent's
    ability to act on the connected system."""
    tenant_id = scope.tenant_id
    row = await token_manager.get(session, tenant_id, provider)
    if row is None:
        return {"disconnected": False, "reason": "not connected"}
    await session.delete(row)
    await session.flush()
    return {"disconnected": True}


# ---- Telegram (no OAuth, fixed bot token) ------------------------------


_BYOA_PROVIDERS = {"xero", "quickbooks", "google", "microsoft", "paypal"}


class ProviderConfigResponse(BaseModel):
    provider: str
    configured: bool  # tenant has saved their own client_id
    source: str  # "tenant" if tenant row exists, else "platform"
    client_id: str  # masked or empty when not configured
    custom_redirect_uri: str | None
    custom_scopes: list[str] | None


class ProviderConfigPayload(BaseModel):
    client_id: str
    client_secret: str
    custom_redirect_uri: str | None = None
    custom_scopes: list[str] | None = None


@router.get("/{provider}/config", response_model=ProviderConfigResponse)
async def get_provider_config(
    provider: str,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> ProviderConfigResponse:
    """Return whether the tenant has saved its own OAuth client credentials.

    Any authenticated user can read this — no secrets are returned (client_id
    is the public OAuth app identifier; client_secret is never echoed).
    """
    if provider not in _BYOA_PROVIDERS:
        raise HTTPException(404, f"BYOA not supported for provider {provider!r}")
    row = await tenant_creds.get(session, tenant_id=scope.tenant_id, provider=provider)
    if row is None:
        return ProviderConfigResponse(
            provider=provider,
            configured=False,
            source="platform",
            client_id="",
            custom_redirect_uri=None,
            custom_scopes=None,
        )
    return ProviderConfigResponse(
        provider=provider,
        configured=True,
        source="tenant",
        client_id=row.client_id,
        custom_redirect_uri=row.custom_redirect_uri,
        custom_scopes=row.custom_scopes,
    )


@router.put("/{provider}/config", response_model=ProviderConfigResponse)
async def put_provider_config(
    provider: str,
    payload: ProviderConfigPayload,
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ProviderConfigResponse:
    """Save the tenant's own OAuth client credentials. Encrypted at rest.

    Admin role required — these credentials authorise every future OAuth
    handshake for this tenant; member users cannot rotate them.
    """
    if provider not in _BYOA_PROVIDERS:
        raise HTTPException(404, f"BYOA not supported for provider {provider!r}")
    try:
        await tenant_creds.save(
            session,
            tenant_id=scope.tenant_id,
            provider=provider,
            client_id=payload.client_id.strip(),
            client_secret=payload.client_secret,
            custom_redirect_uri=(
                payload.custom_redirect_uri.strip()
                if payload.custom_redirect_uri
                else None
            ),
            custom_scopes=payload.custom_scopes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await session.commit()
    return await get_provider_config(provider, scope, session)


@router.delete("/{provider}/config")
async def delete_provider_config(
    provider: str,
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Drop the tenant's BYOA credentials — the connect flow falls back to
    the platform-default app from then on. Admin role required."""
    if provider not in _BYOA_PROVIDERS:
        raise HTTPException(404, f"BYOA not supported for provider {provider!r}")
    removed = await tenant_creds.remove(session, tenant_id=scope.tenant_id, provider=provider)
    await session.commit()
    return {"removed": removed, "provider": provider}


_XERO_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,40}$")


@router.get("/xero/invoice/{xero_invoice_id}/pdf")
async def xero_invoice_pdf(
    xero_invoice_id: str,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream the PDF for one of this tenant's Xero invoices.

    Authentication: any signed-in user in the tenant can view. The Xero
    access token used here is the tenant's own (resolved via XeroClient.
    for_tenant), so a request for an invoice not in this tenant's Xero org
    naturally 404s on the Xero side.

    Frontend renders the result inside an <iframe> in the chat invoice
    receipt; ``inline`` Content-Disposition makes the browser display
    rather than download.
    """
    if not _XERO_UUID_RE.match(xero_invoice_id):
        raise HTTPException(400, "invalid xero_invoice_id")

    from tigeri.integrations.xero import XeroClient

    try:
        client = await XeroClient.for_tenant(session, scope.tenant_id)
        pdf_bytes = await client.fetch_invoice_pdf(xero_invoice_id)
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "NotFound" in msg:
            raise HTTPException(404, "invoice not found in this tenant's Xero org") from e
        raise HTTPException(502, msg) from e

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="invoice-{xero_invoice_id[:8]}.pdf"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.get("/telegram/me")
async def telegram_me() -> dict:
    return await tg_int.get_me()


@router.post("/telegram/link-code")
async def telegram_link_code(
    scope: TenantScope = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mint a single-use code the admin types into Telegram as ``/connect <CODE>``.

    Admin role required — linking a Telegram chat to a tenant means that chat
    receives the tenant's admin notifications and can act under tenant context.
    """
    code, expires_at = await telegram_link.issue(
        session, tenant_id=scope.tenant_id, user_id=scope.user_id
    )
    settings = get_settings()
    bot_username = settings.telegram_bot_username or ""
    return {
        "code": code,
        "expires_at": expires_at.isoformat(),
        "instructions": (
            f"Open @{bot_username} on Telegram and send: /connect {code}"
            if bot_username
            else f"Send /connect {code} to the Tigeri Telegram bot."
        ),
    }


@router.post("/telegram/setup")
async def telegram_setup(
    body: dict = Body(default_factory=dict),  # noqa: B008
    _scope: TenantScope = Depends(require_admin),
) -> dict:
    """Idempotently register the bot's webhook URL with Telegram. Admin role
    required — this rewrites the bot's global webhook target."""
    settings = get_settings()
    public_base = body.get("public_url") or settings.public_api_base_url
    webhook_url = f"{public_base.rstrip('/')}/api/v1/integrations/telegram/webhook"
    if not settings.telegram_webhook_secret:
        raise HTTPException(412, "TELEGRAM_WEBHOOK_SECRET not configured")
    return await tg_int.set_webhook(webhook_url, settings.telegram_webhook_secret)


async def _safe_send(text: str, chat_id: int) -> None:
    """Send a Telegram message but never let an upstream failure 500 our webhook.

    Telegram retries 5xx responses indefinitely, which floods the bot. We log
    and swallow so the webhook always returns 200.
    """
    try:
        await tg_int.send_message(tg_int.TelegramMessage(chat_id=chat_id, text=text))
    except Exception:  # noqa: BLE001
        logger.exception("telegram sendMessage failed")


# ── Quick-start buttons (Telegram /help) ────────────────────────────────
# Each tuple is (button label shown to the user, canned prompt fired into
# the orchestrator on tap). Keep the canned prompt fully self-contained so
# the model has all info and doesn't need follow-ups.

_QUICK_START_PROMPTS: list[tuple[str, str]] = [
    (
        "📊 P&L last 30 days",
        "Run a P&L for the last 30 days and summarise the top 3 lines.",
    ),
    (
        "🧾 Raise sample invoice",
        "Raise a draft invoice for Acme Corp for 5,000 USD, "
        "line item 'Consulting services'. Show me the result here.",
    ),
    (
        "📅 What's on my calendar?",
        "What's on my calendar this week? Just list titles and times.",
    ),
    (
        "🤝 Schedule a meeting",
        "Schedule a 30-minute meeting tomorrow at 10:30 with russo@tigeri.ai. "
        "Title: Demo follow-up. Add a Google Meet link.",
    ),
    (
        "✉️ Email Russo",
        "Email russo@tigeri.ai. Subject: Tigeri pilot update. Body: "
        "Quick note that the platform is up and running, looking forward "
        "to the next sync.",
    ),
    (
        "🔌 Integration status",
        "Show me the status of all my connected integrations.",
    ),
]


async def _send_quickstart_menu(chat_id: int) -> None:
    """Send the /help quick-start menu as a Telegram message with inline
    buttons. Tap → callback_query (qs:<idx>) → fire the canned prompt."""
    keyboard = []
    for idx, (label, _prompt) in enumerate(_QUICK_START_PROMPTS):
        keyboard.append([{"text": label, "callback_data": f"qs:{idx}"}])
    payload = {
        "chat_id": chat_id,
        "text": (
            "👋 Quick-start menu — tap any of these to demo the platform. "
            "Or just message me normally and I'll figure it out."
        ),
        "reply_markup": {"inline_keyboard": keyboard},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(tg_int._bot_url("sendMessage"), json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("quickstart menu send failed")


def _human_tool_step(tool: str) -> str:
    """Map an internal tool name to a friendly progress line for Telegram.
    Falls back to the raw name for tools we haven't curated."""
    return {
        "send_gmail": "✉️ Drafting your email…",
        "list_calendar_events": "📅 Reading your calendar…",
        "create_calendar_event_with_meet": "📅 Setting up the meeting…",
        "list_agents": "🧠 Looking up agents…",
        "list_recent_audit": "🧾 Loading recent activity…",
        "list_integrations_status": "🔌 Checking integrations…",
        "get_connect_url": "🔗 Building a connect link…",
        "invoke_invoice_agent": "🧾 Reading the invoice…",
        "invoke_expense_agent": "💸 Logging the expense…",
        "invoke_admin_agent": "⚙️ Working on it…",
        "invoke_staffing_agent": "👥 Checking rosters…",
        "invoke_booking_agent": "🗓 Setting up the booking…",
        "invoke_financial_reporting_agent": "📊 Running the report…",
        "invoke_contract_management_agent": "📑 Reading contracts…",
        "invoke_client_onboarding_agent": "🆕 Onboarding the client…",
    }.get(tool, f"🔧 {tool}")


def _render_proposal_text(capability: str, args: dict) -> str:
    """Render a brief, human-readable summary of a proposed write action so
    the Telegram user knows what they're confirming. Drops control fields
    (tenant_id / user_id) since they're identical for every action."""
    skip = {"tenant_id", "user_id"}
    head = {
        "send_gmail": "✉️ Send email",
        "create_calendar_event_with_meet": "📅 Create calendar event",
        "invoke_invoice_agent": "🧾 Run invoice agent",
        "invoke_expense_agent": "💸 Run expense agent",
        "invoke_admin_agent": "⚙️ Run admin agent",
        "invoke_staffing_agent": "👥 Run staffing agent",
        "invoke_booking_agent": "🗓 Run booking agent",
        "invoke_contract_management_agent": "📑 Run contract agent",
        "invoke_client_onboarding_agent": "🆕 Run onboarding agent",
    }.get(capability, f"⚡ {capability}")

    lines = [head]
    for k, v in (args or {}).items():
        if k in skip:
            continue
        if isinstance(v, str) and len(v) > 200:
            v = v[:197] + "…"
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


async def _send_proposal_buttons(
    chat_id: int, *, capability: str, args: dict, confirmation_token: str
) -> None:
    """Send a Telegram message with inline [Confirm][Cancel] buttons that
    map back to the pending action via callback_data. Telegram's
    callback_data limit is 64 bytes — confirmation_token is ~43 chars, our
    "cnf:"/"cnl:" prefix adds 4, so total ~47 bytes — fits.
    """
    text = _render_proposal_text(capability, args) + "\n\nConfirm to execute:"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Confirm", "callback_data": f"cnf:{confirmation_token}"},
                    {"text": "❌ Cancel", "callback_data": f"cnl:{confirmation_token}"},
                ]
            ]
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(tg_int._bot_url("sendMessage"), json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "telegram proposal send failed: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:  # noqa: BLE001
        logger.exception("telegram proposal send raised")


async def _resolve_actor_for_chat(
    session: AsyncSession, *, tenant_id: str
) -> str | None:
    """Pick the actor user_id for a Telegram-channel action. Same rule as
    in `_route_to_orchestrator` — first active owner/admin in the linked
    tenant. Returns None if there's nobody usable."""
    from sqlalchemy import select as _select

    from tigeri.auth.models import User as _User

    res = await session.execute(
        _select(_User)
        .where(_User.tenant_id == tenant_id)
        .where(_User.status == "active")
        .where(_User.role.in_(("owner", "admin")))
        .order_by(_User.created_at.asc())
        .limit(1)
    )
    actor = res.scalar_one_or_none()
    return actor.id if actor else None


async def _telegram_answer_callback(
    callback_query_id: str, *, text: str = "", show_alert: bool = False
) -> None:
    """Acknowledge a callback_query so Telegram clears the loading spinner."""
    payload = {
        "callback_query_id": callback_query_id,
        "text": text[:200],
        "show_alert": show_alert,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(tg_int._bot_url("answerCallbackQuery"), json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("answerCallbackQuery failed")


async def _telegram_edit_message(
    chat_id: int, message_id: int, *, text: str
) -> None:
    """Replace the proposal message with a result line (clears the buttons
    so the user can't double-confirm)."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(tg_int._bot_url("editMessageText"), json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("editMessageText failed")


async def _handle_telegram_callback(
    cbq: dict, session: AsyncSession
) -> dict:
    """Process a callback_query from a Telegram inline keyboard. Mirrors
    the security model of /actions/confirm: token + tenant_id check, then
    decrypt + dispatch under PendingActionService."""
    from datetime import UTC, datetime

    from tigeri.actions.dispatch import (  # local import to avoid cycle
        UnknownCapabilityError,
        dispatch_capability,
    )
    from tigeri.actions.service import (
        PendingActionExpired,
        PendingActionInvalid,
        PendingActionService,
    )
    from tigeri.audit_chain.writer import AuditChainWriter, AuditEntry

    cbq_id = cbq.get("id") or ""
    data = cbq.get("data") or ""
    msg = cbq.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    message_id = msg.get("message_id")

    if chat_id is None or not data or ":" not in data:
        await _telegram_answer_callback(cbq_id, text="bad callback")
        return {"ok": True, "ignored": "bad_callback"}

    op, _, token = data.partition(":")

    # Quick-start tap: re-route the canned prompt through the orchestrator
    # exactly as if the user had typed it. Acknowledge fast so the spinner
    # clears, then run the chat turn under the resolved tenant + actor.
    if op == "qs":
        try:
            idx = int(token)
            label, prompt = _QUICK_START_PROMPTS[idx]
        except (ValueError, IndexError):
            await _telegram_answer_callback(cbq_id, text="unknown shortcut")
            return {"ok": True, "ignored": "bad_quickstart_index"}
        await _telegram_answer_callback(cbq_id, text=label)
        tenant_id_qs = await tg_int.find_tenant_for_chat(session, int(chat_id))
        if tenant_id_qs is None:
            await _safe_send(
                "This chat isn't linked to a tenant yet — send /connect <code> first.",
                int(chat_id),
            )
            return {"ok": True, "rejected": "unlinked_chat"}
        actor_id_qs = await _resolve_actor_for_chat(session, tenant_id=tenant_id_qs)
        if actor_id_qs is None:
            await _safe_send(
                "This tenant has no active owner/admin user, so I can't act on "
                "your behalf yet.",
                int(chat_id),
            )
            return {"ok": True, "rejected": "no_actor"}
        # Echo the canned prompt to the chat so the user can see what was
        # fired (helpful during a demo) before the orchestrator replies.
        await _safe_send(f"› {prompt}", int(chat_id))
        return await _route_to_orchestrator(
            session=session,
            chat_id=int(chat_id),
            tenant_id=tenant_id_qs,
            user_id=actor_id_qs,
            user_message=prompt,
        )

    if op not in ("cnf", "cnl") or not token:
        await _telegram_answer_callback(cbq_id, text="bad callback")
        return {"ok": True, "ignored": "bad_callback_op"}

    tenant_id = await tg_int.find_tenant_for_chat(session, int(chat_id))
    if tenant_id is None:
        await _telegram_answer_callback(
            cbq_id, text="this chat isn't linked to a tenant", show_alert=True
        )
        return {"ok": True, "rejected": "unlinked_chat"}

    actor_id = await _resolve_actor_for_chat(session, tenant_id=tenant_id)
    if actor_id is None:
        await _telegram_answer_callback(
            cbq_id,
            text="tenant has no active owner/admin; cannot execute",
            show_alert=True,
        )
        return {"ok": True, "rejected": "no_actor"}

    svc = PendingActionService(session)
    audit = AuditChainWriter(session)

    if op == "cnl":
        try:
            cancelled = await svc.cancel(
                confirmation_token=token, tenant_id=tenant_id
            )
        except PendingActionInvalid as e:
            await _telegram_answer_callback(cbq_id, text=str(e)[:180])
            await session.commit()
            return {"ok": True, "rejected": "invalid_token"}
        await audit.write(
            AuditEntry(
                tenant_id=tenant_id,
                user_id=actor_id,
                event_type="action_cancelled",
                capability=cancelled.capability,
                result="success",
                idempotency_key=cancelled.idempotency_key,
            )
        )
        await session.commit()
        await _telegram_answer_callback(cbq_id, text="cancelled")
        if message_id is not None:
            await _telegram_edit_message(
                int(chat_id), int(message_id), text="❌ Cancelled."
            )
        return {"ok": True, "cancelled": cancelled.id}

    # op == "cnf" — confirm + dispatch
    try:
        action = await svc.confirm(
            confirmation_token=token, tenant_id=tenant_id
        )
    except PendingActionExpired:
        await audit.write(
            AuditEntry(
                tenant_id=tenant_id,
                user_id=actor_id,
                event_type="action_expired",
                result="expired",
            )
        )
        await session.commit()
        await _telegram_answer_callback(cbq_id, text="expired", show_alert=True)
        if message_id is not None:
            await _telegram_edit_message(
                int(chat_id), int(message_id), text="⌛ Expired before you confirmed."
            )
        return {"ok": True, "expired": True}
    except PendingActionInvalid as e:
        await _telegram_answer_callback(cbq_id, text=str(e)[:180])
        await session.commit()
        return {"ok": True, "rejected": "invalid_token"}

    await audit.write(
        AuditEntry(
            tenant_id=tenant_id,
            user_id=actor_id,
            event_type="action_confirmed",
            capability=action.capability,
            result="success",
            idempotency_key=action.idempotency_key,
        )
    )

    try:
        parameters = await svc.decrypt_parameters(action)
    except Exception as e:  # noqa: BLE001
        await svc.mark_failed(action_id=action.id, error=f"decrypt: {e}")
        await audit.write(
            AuditEntry(
                tenant_id=tenant_id,
                user_id=actor_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail=f"decrypt: {e}",
            )
        )
        await session.commit()
        await _telegram_answer_callback(cbq_id, text="decrypt failed", show_alert=True)
        if message_id is not None:
            await _telegram_edit_message(
                int(chat_id), int(message_id), text="❌ Failed: decrypt error."
            )
        return {"ok": True, "decrypt_failed": True}

    public_base = get_settings().public_api_base_url
    try:
        result = await dispatch_capability(
            capability=action.capability,
            parameters=parameters,
            session=session,
            tenant_id=tenant_id,
            user_id=actor_id,
            session_id=f"telegram:{chat_id}",
            public_base_url=public_base,
        )
    except UnknownCapabilityError:
        await svc.mark_failed(action_id=action.id, error="unknown capability")
        await audit.write(
            AuditEntry(
                tenant_id=tenant_id,
                user_id=actor_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail="unknown capability",
            )
        )
        await session.commit()
        await _telegram_answer_callback(
            cbq_id, text=f"unknown capability {action.capability}", show_alert=True
        )
        if message_id is not None:
            await _telegram_edit_message(
                int(chat_id), int(message_id),
                text=f"❌ Failed: unknown capability {action.capability}",
            )
        return {"ok": True, "unknown_capability": True}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        await svc.mark_failed(action_id=action.id, error=err)
        await audit.write(
            AuditEntry(
                tenant_id=tenant_id,
                user_id=actor_id,
                event_type="capability_failed",
                capability=action.capability,
                result="failure",
                error_detail=err[:500],
                idempotency_key=action.idempotency_key,
            )
        )
        await session.commit()
        await _telegram_answer_callback(
            cbq_id, text=err[:180], show_alert=True
        )
        if message_id is not None:
            await _telegram_edit_message(
                int(chat_id), int(message_id), text=f"❌ Failed: {err[:300]}"
            )
        return {"ok": True, "failed": True, "error": err}

    await svc.mark_executed(action_id=action.id, result=result)
    await audit.write(
        AuditEntry(
            tenant_id=tenant_id,
            user_id=actor_id,
            event_type="capability_invoked",
            capability=action.capability,
            result="success",
            idempotency_key=action.idempotency_key,
        )
    )
    await session.commit()

    summary = _summarise_result(action.capability, result)
    await _telegram_answer_callback(cbq_id, text="done")
    if message_id is not None:
        await _telegram_edit_message(
            int(chat_id), int(message_id),
            text=f"✅ {action.capability} executed.\n{summary}",
        )
    return {"ok": True, "executed": action.id}


def _summarise_result(capability: str, result: dict | None) -> str:
    """One-line human summary of the dispatch result for the Telegram message.
    Plain text only — escapes happen in editMessageText if MarkdownV2 is used."""
    if not isinstance(result, dict):
        return ""
    if capability == "send_gmail":
        if result.get("error"):
            return f"❌ {result['error']}"
        return (
            f"to: {result.get('to', '?')}\n"
            f"subject: {result.get('subject', '?')}\n"
            f"message_id: {result.get('message_id', '?')}"
        )
    if capability == "create_calendar_event_with_meet":
        if result.get("error"):
            return f"❌ {result['error']}"
        link = result.get("html_link") or ""
        meet = result.get("meet_link") or ""
        attendees = result.get("attendees") or []
        out = f"event_id: {result.get('event_id', '?')}"
        if attendees:
            out += f"\nattendees: {', '.join(attendees)}"
        if link:
            out += f"\nCalendar: {link}"
        if meet:
            out += f"\nMeet: {meet}"
        return out
    if capability == "invoke_invoice_agent":
        if result.get("error"):
            return f"❌ {result['error']}"
        invoice_id = result.get("invoice_id") or "?"
        url = result.get("posting_url") or ""
        ref = result.get("posting_reference") or ""
        out = f"invoice_id: {invoice_id}"
        if ref:
            out += f"\nposting_reference: {ref}"
        if url:
            out += f"\nView: {url}"
        return out
    if result.get("error"):
        return f"❌ {result['error']}"
    if isinstance(result.get("ok"), bool):
        return "ok" if result["ok"] else f"error: {result.get('error', '?')}"
    return ""


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if (
        not settings.telegram_webhook_secret
        or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(401, "invalid secret token")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True, "ignored": "non-json body"}

    # Inline-keyboard taps arrive as a callback_query update (no `message`).
    # Route those to the confirm/cancel handler before we try to read text.
    cbq = update.get("callback_query")
    if cbq is not None:
        try:
            return await _handle_telegram_callback(cbq, session)
        except Exception:  # noqa: BLE001
            logger.exception("telegram callback_query handler raised")
            await session.rollback()
            return {"ok": True, "ignored": "callback_handler_exception"}

    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    sender = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    logger.info("telegram_update", chat_id=chat_id, text=text[:80])

    if chat_id is None:
        return {"ok": True, "ignored": "no chat_id"}

    parts = text.split()
    if len(parts) >= 2 and parts[0] in {"/start", "/connect"}:
        # /connect <CODE> — verify a one-time link code minted by an authenticated
        # web-app user. Replaces the previous "/connect <tenant_id>" flow which
        # let any Telegram user claim any tenant.
        try:
            tigeri_tenant_id = await telegram_link.consume(session, code=parts[1])
        except telegram_link.InvalidLinkCodeError as e:
            logger.warning("telegram /connect rejected: %s", e)
            await _safe_send(
                "That link code didn't work — it may be expired, already used, "
                "or wrong. Generate a fresh one in the Tigeri web app under "
                "Integrations → Telegram.",
                int(chat_id),
            )
            return {"ok": True, "rejected": "invalid_link_code"}

        try:
            await tg_int.remember_chat(session, tigeri_tenant_id, int(chat_id), sender)
            await session.commit()
        except Exception:
            logger.exception("remember_chat failed")
            await session.rollback()
        await _safe_send(
            f"Linked to Tigeri tenant {tigeri_tenant_id}. "
            "Admin Agent notifications will arrive here.",
            int(chat_id),
        )
        return {"ok": True, "linked_tenant": tigeri_tenant_id}

    if text.startswith("/start") or text.startswith("/help") or text == "":
        # If the chat is already linked, show quick-start inline buttons so
        # the user (and demo audience) can fire canned prompts with a single
        # tap instead of typing. Unlinked chats get the connect instructions.
        linked = await tg_int.find_tenant_for_chat(session, int(chat_id))
        if linked is not None:
            await _send_quickstart_menu(int(chat_id))
            return {"ok": True}
        await _safe_send(
            "Hi — I'm Tigeri, your business automation assistant.\n\n"
            "Step 1 — link your tenant:\n"
            "    1. Sign in to the Tigeri web app.\n"
            "    2. Go to Integrations → Telegram → Generate code.\n"
            "    3. Send /connect <code> here (codes expire in 5 minutes).\n\n"
            "Step 2 — once linked, send /help to see quick-start buttons.",
            int(chat_id),
        )
        return {"ok": True}

    # Free-form text — route to A2UI orchestrator if this chat is linked.
    linked_tenant = await tg_int.find_tenant_for_chat(session, int(chat_id))
    if linked_tenant is None:
        await _safe_send(
            "This chat isn't linked to a Tigeri tenant yet.\n\n"
            "1. Sign in to the Tigeri web app.\n"
            "2. Go to Integrations → Telegram → Generate code.\n"
            "3. Send /connect <that-code> here (codes expire in 5 minutes).",
            int(chat_id),
        )
        return {"ok": True}

    # Telegram's `from.id` is a Telegram user id, not a Tigeri user id —
    # passing it straight through fails the FK on pending_actions.user_id.
    # Attribute Telegram-channel actions to the linked tenant's owner (or
    # any active admin) so writes can persist; the audit chain still records
    # channel='telegram' so the provenance isn't lost.
    from sqlalchemy import select as _select

    from tigeri.auth.models import User as _User

    actor = await session.execute(
        _select(_User)
        .where(_User.tenant_id == linked_tenant)
        .where(_User.status == "active")
        .where(_User.role.in_(("owner", "admin")))
        .order_by(_User.created_at.asc())
        .limit(1)
    )
    actor_row = actor.scalar_one_or_none()
    if actor_row is None:
        await _safe_send(
            "This tenant has no active owner/admin user, so I can't act on "
            "your behalf yet. Add one in the web app and try again.",
            int(chat_id),
        )
        return {"ok": True, "rejected": "no_actor"}

    return await _route_to_orchestrator(
        session=session,
        chat_id=int(chat_id),
        tenant_id=linked_tenant,
        user_id=actor_row.id,
        user_message=text,
    )


async def _route_to_orchestrator(
    *,
    session: AsyncSession,
    chat_id: int,
    tenant_id: str,
    user_id: str,
    user_message: str,
) -> dict:
    """Run one A2UI orchestrator turn for a Telegram message and reply via Telegram."""

    from tigeri.api.routes.chat import stream_chat as _orch_stream
    from tigeri.chat import store as _chat_store

    text_buf = ""
    tool_steps: list[str] = []
    agent_runs: list[str] = []
    error_msg: str | None = None

    # Send a typing indicator so the user sees the bot is working
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                tg_int._bot_url("sendChatAction"),
                json={"chat_id": chat_id, "action": "typing"},
            )
    except Exception:  # noqa: BLE001
        pass

    # Load this chat's prior turns so the orchestrator has memory across
    # messages — without this the bot has amnesia and re-asks the same
    # questions every turn (the web client passes history from its own
    # state; Telegram has no client-side state, so we rebuild it here).
    session_id = f"telegram:{chat_id}"
    thread = await _chat_store.get_or_create_thread(
        session, tenant_id=tenant_id, user_id=user_id, session_id=session_id
    )
    prior_msgs = await _chat_store.list_messages(session, thread.id)
    history: list[dict] = [
        {"role": m.role, "content": _chat_store.decrypted_content(m)}
        for m in prior_msgs
        if m.role in ("user", "assistant")
    ]

    proposals: list[dict] = []
    try:
        async for ev in _orch_stream(
            user_message=user_message,
            history=history,
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
        ):
            etype = ev.get("type")
            if etype == "agent_text" and ev.get("content"):
                text_buf += ev["content"]
            elif etype == "tool_call":
                tool_steps.append(_human_tool_step(ev.get("tool", "?")))
            elif etype == "tool_proposed":
                # Buffer until after the stream — we send each as its own
                # message with [Confirm][Cancel] buttons attached.
                proposals.append(ev)
            elif etype == "agent_run":
                agent_runs.append(
                    f"🤖 {ev.get('agent_id', '?')} — {ev.get('summary', '')[:120]}"
                )
            elif etype == "error":
                error_msg = ev.get("message") or "unknown error"
    except Exception as e:  # noqa: BLE001
        error_msg = f"{type(e).__name__}: {e}"

    parts: list[str] = []
    if tool_steps:
        parts.append("\n".join(dict.fromkeys(tool_steps)))  # de-dupe, preserve order
    if agent_runs:
        parts.append("\n".join(agent_runs))
    if text_buf.strip():
        parts.append(text_buf.strip())
    if error_msg:
        parts.append(f"⚠️ {error_msg}")
    reply = "\n\n".join(parts).strip()

    # Send the regular reply text (if any) before the proposal cards so the
    # buttons sit at the bottom of the conversation where the user will see
    # them.
    if reply:
        # Telegram limit is 4096 chars per message — split if needed
        for chunk in _split_for_telegram(reply, 3900):
            await _safe_send(chunk, chat_id)
    elif not proposals:
        await _safe_send("(no response)", chat_id)

    # Each proposed write action gets its own message with [Confirm][Cancel]
    # buttons. Tap → callback_query → /telegram/webhook → confirm + dispatch.
    for prop in proposals:
        token = prop.get("confirmation_token")
        if not token:
            continue
        await _send_proposal_buttons(
            chat_id,
            capability=prop.get("capability") or "?",
            args=prop.get("args") or {},
            confirmation_token=token,
        )

    return {"ok": True, "tenant": tenant_id, "proposals": len(proposals)}


def _split_for_telegram(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Prefer to split on a newline near the limit
        cut = remaining.rfind("\n", 0, max_len)
        if cut < int(max_len * 0.5):
            cut = max_len
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


# ---- WhatsApp (no OAuth, single 360dialog API key, per-tenant opt-in) ---


@router.get("/whatsapp/whoami")
async def whatsapp_whoami() -> dict:
    """Confirms the 360dialog API key works (independent of any tenant)."""
    return await wa_int.whoami()


class WhatsAppOptIn(BaseModel):
    recipient_msisdn: str  # E.164 without leading + (e.g. 9995322303)
    note: str = ""


@router.post("/whatsapp/optin")
async def whatsapp_optin(
    body: WhatsAppOptIn,
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(require_admin),
) -> dict:
    """Record the recipient phone the tenant wants Admin Agent comms on.

    Admin role required — outbound WhatsApp messaging on behalf of a tenant
    is regulated comms; member users cannot redirect it."""
    msisdn = body.recipient_msisdn.lstrip("+").strip()
    if not msisdn.isdigit() or len(msisdn) < 8:
        raise HTTPException(400, "recipient_msisdn must be E.164 digits, no '+'")
    await wa_int.remember_optin(
        session, tenant_id=scope.tenant_id, recipient_msisdn=msisdn, note=body.note
    )
    await session.commit()
    return {"ok": True, "recipient_msisdn": msisdn}


class WhatsAppTestSend(BaseModel):
    text: str


@router.post("/whatsapp/test-send")
async def whatsapp_test_send(
    body: WhatsAppTestSend,
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(require_admin),
) -> dict:
    """Send the recorded recipient a one-off WhatsApp message — used by the UI
    'Send test' button to confirm wiring. Admin role required."""
    msisdn = await wa_int.get_recipient(session, scope.tenant_id)
    if not msisdn:
        raise HTTPException(412, "no recipient on file — call /whatsapp/optin first")
    return await wa_int.send_text(wa_int.WhatsAppText(to_msisdn=msisdn, text=body.text))
