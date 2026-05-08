"""Contain integrations backend logic."""
import base64
import json
import secrets
from datetime import datetime, timezone
from typing import Optional
import logging
import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth.deps import get_current_user, require_admin
from config.db_pool import get_conn
from config.settings import settings
from integrations.oauth_providers import (
    ALL_PROVIDERS,
    APIKEY_PROVIDERS,
    OAUTH_PROVIDERS,
    build_auth_url,
    get_redirect_uri,
)
from integrations.token_manager import bootstrap_token
from security.audit import log_action
from security.encryption import encrypt_secret
from integrations.resilience import CircuitBreaker
import re

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])
_SENDER_RE = re.compile(r"^\d{7,15}$")

_redis = redis.from_url(settings.redis_url, decode_responses=True)

# Constant for state time-to-live.
STATE_TTL = 600
# Constant for integration state prefix.
INTEGRATION_STATE_PREFIX = "integration:oauth_state:"
# Constant for integration status prefix.
INTEGRATION_STATUS_PREFIX = "integration:status:"


class ApiKeyConnectRequest(BaseModel):
    """Represent the ApiKeyConnectRequest component and its related behavior."""
    provider: str
    api_key: str
    extra: Optional[dict] = None


class StripeWebhookRequest(BaseModel):
    """Represent the StripeWebhookRequest component and its related behavior."""
    webhook_secret: str


def _store_oauth_state(state: str, client_id: str, provider: str):
    """Execute store oauth state."""
    payload = json.dumps({"client_id": client_id, "provider": provider})
    _redis.setex(f"{INTEGRATION_STATE_PREFIX}{state}", STATE_TTL, payload)


def _pop_oauth_state(state: str) -> Optional[dict]:
    """Execute pop oauth state."""
    key = f"{INTEGRATION_STATE_PREFIX}{state}"
    raw = _redis.get(key)
    if not raw:
        return None
    _redis.delete(key)
    return json.loads(str(raw))


def _mark_connected(client_id: str, provider: str, scopes: Optional[str] = None):
    """Execute mark connected."""
    payload = {
        "connected": True,
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "scopes": scopes or "",
    }
    _redis.set(f"{INTEGRATION_STATUS_PREFIX}{client_id}:{provider}", json.dumps(payload))
    _persist_integration_status(client_id, provider, True, scopes)


def _mark_disconnected(client_id: str, provider: str):
    """Execute mark disconnected."""
    _redis.delete(f"{INTEGRATION_STATUS_PREFIX}{client_id}:{provider}")
    _persist_integration_status(client_id, provider, False, None)


def _get_status(client_id: str, provider: str) -> dict:
    """Return status."""
    raw = _redis.get(f"{INTEGRATION_STATUS_PREFIX}{client_id}:{provider}")
    if raw:
        return json.loads(str(raw))
    return _load_integration_status_from_db(client_id, provider)


def _persist_integration_status(client_id: str, provider: str, connected: bool, scopes: Optional[str]):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO client_integrations (client_id, provider, connected, scopes, connected_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (client_id, provider)
                DO UPDATE SET
                    connected = EXCLUDED.connected,
                    scopes = EXCLUDED.scopes,
                    connected_at = CASE WHEN EXCLUDED.connected = TRUE THEN NOW() ELSE client_integrations.connected_at END,
                    updated_at = NOW()
            """, (client_id, provider, connected, scopes))
            cur.close()
    except Exception as e:
        logger.error("Failed to persist integration status: %s", e)


def _load_integration_status_from_db(client_id: str, provider: str) -> dict:
    """Load integration status from db."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT connected, connected_at, scopes FROM client_integrations
                WHERE client_id = %s AND provider = %s
            """, (client_id, provider))
            row = cur.fetchone()
            cur.close()
        if row:
            return {
                "connected": row[0],
                "connected_at": str(row[1]) if row[1] else None,
                "scopes": row[2],
            }
    except Exception:
        pass
    return {"connected": False, "connected_at": None, "scopes": None}


def _store_provider_meta(client_id: str, provider: str, meta: dict):
    """Execute store provider meta."""
    key = f"integration:meta:{client_id}:{provider}"
    existing_raw = _redis.get(key)
    existing = json.loads(str(existing_raw)) if existing_raw else {}
    existing.update(meta)
    _redis.set(key, json.dumps(existing))
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO client_integrations (client_id, provider, connected, meta, updated_at)
                VALUES (%s, %s, TRUE, %s::jsonb, NOW())
                ON CONFLICT (client_id, provider)
                DO UPDATE SET
                    meta = client_integrations.meta || %s::jsonb,
                    updated_at = NOW()
            """, (client_id, provider, json.dumps(meta), json.dumps(meta)))
            cur.close()
    except Exception as e:
        logger.error("Failed to persist provider meta: %s", e)


def _clear_provider_meta(client_id: str, provider: str):
    """Execute clear provider meta."""
    _redis.delete(f"integration:meta:{client_id}:{provider}")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE client_integrations
                SET meta = '{}'::jsonb, updated_at = NOW()
                WHERE client_id = %s AND provider = %s
                """,
                (client_id, provider),
            )
            cur.close()
    except Exception as e:
        import sys
        logger.error("Failed to clear provider meta: %s", e)


def get_provider_meta(client_id: str, provider: str) -> dict:
    """Return provider meta."""
    key = f"integration:meta:{client_id}:{provider}"
    raw = _redis.get(key)
    if raw:
        return json.loads(str(raw))
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT meta FROM client_integrations
                WHERE client_id = %s AND provider = %s
            """, (client_id, provider))
            row = cur.fetchone()
            cur.close()
        if row and row[0]:
            _redis.set(key, json.dumps(row[0]))
            return row[0]
    except Exception:
        pass
    return {}


@router.get("/providers")
def list_providers():
    """List providers."""
    result = []
    for provider, cfg in ALL_PROVIDERS.items():
        entry = {
            "provider": provider,
            "label": cfg["label"],
            "category": cfg["category"],
            "auth_type": cfg["auth_type"],
        }
        if cfg["auth_type"] == "apikey":
            entry["field_label"] = cfg.get("field_label", "API Key")
            entry["field_placeholder"] = cfg.get("field_placeholder", "")
            entry["extra_fields"] = cfg.get("extra_fields", [])
        result.append(entry)
    return {"providers": result}


@router.get("/status/{client_id}")
def integration_status(client_id: str, user: dict = Depends(get_current_user)):
    """Execute integration status."""
    if user["client_id"] != client_id and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    statuses = []
    for provider, cfg in ALL_PROVIDERS.items():
        status = _get_status(client_id, provider)
        statuses.append({
            "provider": provider,
            "label": cfg["label"],
            "category": cfg["category"],
            "auth_type": cfg["auth_type"],
            "connected": status.get("connected", False),
            "connected_at": status.get("connected_at"),
            "scopes": status.get("scopes"),
        })
    return {"integrations": statuses}


@router.get("/connect/{provider}")
def initiate_oauth(provider: str, user: dict = Depends(get_current_user)):
    """Execute initiate oauth."""
    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown or non-OAuth provider: {provider}")
    client_id = user.get("client_id") or user["id"]
    state = secrets.token_urlsafe(24)
    _store_oauth_state(state, client_id, provider)
    auth_url = build_auth_url(provider, state)
    return {"auth_url": auth_url, "provider": provider}


@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    realm_id: Optional[str] = Query(default=None, alias="realmId"),
    error: Optional[str] = Query(default=None),
):
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error={error}&provider={provider}",
            status_code=302,
        )
    state_data = _pop_oauth_state(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    client_id = state_data["client_id"]
    if state_data["provider"] != provider:
        raise HTTPException(status_code=400, detail="Provider mismatch")

    try:
        tokens = await _exchange_code(provider, code)
    except Exception as e:
        logger.error("Token exchange failed provider=%s client=%s: %s", provider, client_id, e)
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error=token_exchange_failed&provider={provider}",
            status_code=302,
        )

    access_token = tokens["access_token"]
    expires_in = tokens.get("expires_in", 3600)
    refresh_token = tokens.get("refresh_token", "")
    refresh_token_expires_in = tokens.get("refresh_token_expires_in")

    logger.info(
        "OAuth tokens received provider=%s client=%s has_refresh_token=%s expires_in=%s",
        provider, client_id, bool(refresh_token), expires_in,
    )

    if provider == "outlook":
        await _register_ms_subscription(client_id, access_token)
        logger.info("Outlook MS subscription registered client=%s", client_id)

    if provider == "google":
        await _register_google_watches(client_id=client_id, access_token=access_token)
        logger.info("Google watches registered client=%s", client_id)

    if provider == "paypal":
        webhook_id = await _register_paypal_webhook(client_id, access_token)
        if webhook_id:
            _store_provider_meta(client_id, "paypal", {"webhook_id": webhook_id})
            logger.info("PayPal webhook_id stored: %s client=%s", webhook_id, client_id)
        else:
            logger.error("PayPal webhook registration failed client=%s", client_id)

    bootstrap_token(
        service=f"{provider}:{client_id}",
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        refresh_token_expires_in=refresh_token_expires_in,
    )
    logger.info("Token bootstrapped provider=%s client=%s", provider, client_id)

    if provider == "quickbooks":
        if realm_id:
            _store_provider_meta(client_id, "quickbooks", {"realm_id": realm_id})
            logger.info("QuickBooks realm_id stored: %s client=%s", realm_id, client_id)
        else:
            logger.error("QuickBooks realm_id missing from callback client=%s", client_id)
        _redis.delete(f"quickbooks:org_currency:{client_id}")
        logger.info("QuickBooks org_currency cache busted client=%s", client_id)

    if provider == "xero":
        tenant_id = await _fetch_xero_tenant(access_token)
        if tenant_id:
            _store_provider_meta(client_id, "xero", {"tenant_id": tenant_id})
            logger.info("Xero tenant_id stored: %s client=%s", tenant_id, client_id)
        else:
            logger.error("Xero tenant_id fetch failed — Xero API calls will fail client=%s", client_id)

    service = f"{provider}:{client_id}"
    CircuitBreaker(service).reset()

    scopes = OAUTH_PROVIDERS[provider]["scopes"]
    _mark_connected(client_id, provider, scopes)
    log_action(client_id, "integrations", f"connect_{provider}", provider, {"connected": True}, "success")

    return RedirectResponse(
        url=f"{settings.frontend_url}/client-dashboard/integration",
        status_code=302,
    )



@router.post("/connect/apikey")
async def connect_apikey(
    body: ApiKeyConnectRequest,
    user: dict = Depends(get_current_user),
):
    provider = body.provider
    if provider not in APIKEY_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown API key provider: {provider}",
        )
    client_id = user.get("client_id") or user["id"]
    cfg = APIKEY_PROVIDERS[provider]
    await _validate_apikey(provider, body.api_key, cfg)

    if provider == "telegram":
        # unchanged - already works perfectly
        bot_info = await _fetch_telegram_bot_info(body.api_key)
        webhook_url = f"{settings.backend_url}/webhooks/telegram"
        async with httpx.AsyncClient(timeout=10) as hclient:
            r = await hclient.post(
                f"https://api.telegram.org/bot{body.api_key}/setWebhook",
                data={"url": webhook_url, "secret_token": client_id},
            )
            webhook_ok = r.json().get("ok", False)
        _store_provider_meta(client_id, "telegram", {
            "bot_username": bot_info.get("username"),
            "access_token": encrypt_secret(body.api_key),
            "webhook_registered": webhook_ok,
            "webhook_url": webhook_url,
        })
        from config.channel_registry import register_channel_token
        register_channel_token(
            "telegram", client_id, client_id, webhook_url, webhook_ok
        )

    elif provider == "whatsapp":
        sandbox = settings.env == "development"
        base = (
            "https://waba-sandbox.360dialog.io"
            if sandbox
            else "https://waba.360dialog.io"
        )
        
        webhook_url = f"{settings.backend_url}/webhooks/whatsapp/{client_id}"
        async with httpx.AsyncClient(timeout=15) as hclient:
            r = await hclient.post(
                f"{base}/v1/configs/webhook",
                headers={
                    "D360-API-KEY": body.api_key,
                    "Content-Type": "application/json",
                },
                json={"url": webhook_url},
            )

        if r.status_code == 401:
            raise HTTPException(
                status_code=400,
                detail="Invalid WhatsApp API key. "
                    "Please check your 360dialog key.",
            )

        webhook_ok = r.status_code == 200
        if not webhook_ok:
            async with httpx.AsyncClient(timeout=10) as hclient:
                check = await hclient.get(
                    f"{base}/v1/configs/webhook",
                    headers={"D360-API-KEY": body.api_key},
                )
            webhook_ok = check.json().get("url") == webhook_url

        if not webhook_ok:
            raise HTTPException(
                status_code=500,
                detail="WhatsApp webhook registration failed. "
                    "Ensure your server is publicly accessible.",
            )
        phone_number = ""
        if body.extra and body.extra.get("phone_number"):
            phone_number = (
                body.extra["phone_number"]
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
                .strip()
            )

        _store_provider_meta(client_id, "whatsapp", {
            "webhook_set": webhook_ok,
            "webhook_url": webhook_url,
            "sandbox": sandbox,
            "phone_number": phone_number,
            "access_token": encrypt_secret(body.api_key),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        })

        from config.channel_registry import register_channel_token
        register_channel_token(
            "whatsapp", body.api_key, client_id, webhook_url, webhook_ok
        )

        if phone_number and _SENDER_RE.match(phone_number):
            _redis.setex(
                f"whatsapp:phone:{phone_number}",
                86400 * 365,
                client_id,
            )

        logger.info(
            "WhatsApp connected client=%s webhook=%s sandbox=%s",
            client_id, webhook_url, sandbox,
        )

    elif provider == "twilio_whatsapp":
        account_sid = (body.extra or {}).get("account_sid", "").strip()
        phone_number = (
            (body.extra or {}).get("phone_number", "")
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .strip()
        )
        if not account_sid:
            raise HTTPException(
                status_code=400,
                detail="Account SID is required for Twilio WhatsApp.",
            )
        if not phone_number:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp phone number is required for Twilio WhatsApp.",
            )

        # Validate credentials by calling the Twilio Accounts API.
        async with httpx.AsyncClient(timeout=10) as hclient:
            r = await hclient.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
                auth=(account_sid, body.api_key),
            )
        if r.status_code == 401:
            raise HTTPException(
                status_code=400,
                detail="Invalid Twilio credentials. Check your Account SID and Auth Token.",
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Twilio validation failed ({r.status_code}). "
                       "Ensure your Account SID and Auth Token are correct.",
            )

        webhook_url = f"{settings.backend_url}/webhooks/twilio/{client_id}"

        # Automatically configure all webhooks on the WhatsApp Sender via the
        # Twilio Senders API so the user never has to touch the Twilio console.
        webhook_registered = False
        sender_sid = None
        try:
            formatted_phone = f"whatsapp:+{phone_number}"

            # Step 1 – list all WhatsApp senders and find the one matching this number.
            async with httpx.AsyncClient(timeout=10) as hclient:
                list_resp = await hclient.get(
                    "https://messaging.twilio.com/v2/Channels/Senders",
                    auth=(account_sid, body.api_key),
                    params={"Channel": "whatsapp", "PageSize": 100},
                )
            if list_resp.status_code == 200:
                senders = list_resp.json().get("senders", [])
                for s in senders:
                    if s.get("sender_id", "").replace(" ", "") == formatted_phone:
                        sender_sid = s["sid"]
                        break

            if sender_sid:
                # Step 2 – update the sender with all webhook endpoints via the Senders API.
                async with httpx.AsyncClient(timeout=10) as hclient:
                    update_resp = await hclient.post(
                        f"https://messaging.twilio.com/v2/Channels/Senders/{sender_sid}",
                        auth=(account_sid, body.api_key),
                        json={
                            "webhook": {
                                "callback_url": webhook_url,
                                "callback_method": "POST",
                                "fallback_url": webhook_url,
                                "fallback_method": "POST",
                            }
                        },
                    )
                webhook_registered = update_resp.status_code == 200
                if not webhook_registered:
                    logger.warning(
                        "Twilio Senders API webhook update failed sid=%s status=%s body=%s",
                        sender_sid, update_resp.status_code, update_resp.text,
                    )
                else:
                    logger.info(
                        "Twilio webhook auto-configured sender_sid=%s webhook=%s",
                        sender_sid, webhook_url,
                    )
            else:
                logger.warning(
                    "Twilio WhatsApp sender %s not found in account %s — "
                    "ensure the number is registered as a WhatsApp Sender in Twilio Console",
                    formatted_phone, account_sid,
                )
        except Exception as exc:
            logger.warning("Twilio webhook auto-register error: %s", exc)

        _store_provider_meta(client_id, "twilio_whatsapp", {
            "account_sid": account_sid,
            "from_number": phone_number,
            "sender_sid": sender_sid,
            "webhook_url": webhook_url,
            "webhook_registered": webhook_registered,
            "access_token": encrypt_secret(body.api_key),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        })

        from config.channel_registry import register_channel_token
        register_channel_token(
            "twilio_whatsapp", phone_number, client_id, webhook_url, True
        )

        if phone_number:
            _redis.setex(
                f"twilio_whatsapp:phone:{phone_number}",
                86400 * 365,
                client_id,
            )

        logger.info(
            "Twilio WhatsApp connected client=%s webhook=%s phone=%s",
            client_id, webhook_url, phone_number,
        )

    else:
        _store_provider_meta(client_id, provider, {
            "access_token": encrypt_secret(body.api_key),
        })

    bootstrap_token(
        service=f"{provider}:{client_id}",
        access_token=body.api_key,
        expires_in=86400 * 365,
        refresh_token="",
    )

    service = f"{provider}:{client_id}"
    CircuitBreaker(service).reset()

    _mark_connected(client_id, provider)
    log_action(
        client_id, "integrations", f"connect_{provider}",
        provider, {"connected": True}, "success",
    )
    return {"status": "connected", "provider": provider}


@router.post("/admin/integrations/{client_id}/setup-webhook/{provider}")
async def admin_setup_webhook(
    client_id: str,
    provider: str,
    admin: dict = Depends(require_admin)
):
    """Execute admin setup webhook."""
    if provider == "telegram":
        try:
            from integrations.token_manager import _get_stored
            stored = _get_stored(f"telegram:{client_id}")
            if not stored or not stored.get("access_token"):
                raise HTTPException(status_code=400, detail="Telegram not connected for this client")
            bot_token = stored["access_token"]
            webhook_url = f"{settings.backend_url}/webhooks/telegram"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/setWebhook",
                    data={
                        "url": webhook_url,
                        "secret_token": client_id,
                    }
                )
                result = r.json()
            if result.get("ok"):
                from config.channel_registry import register_channel_token
                register_channel_token(
                    channel="telegram",
                    token=client_id,
                    client_id=client_id,
                    webhook_url=webhook_url,
                    webhook_verified=True,
                )
                return {"status": "webhook_set", "provider": "telegram", "client_id": client_id}
            raise HTTPException(status_code=500, detail=f"Telegram error: {result.get('description')}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if provider == "whatsapp":
        try:
            from integrations.token_manager import _get_stored
            stored = _get_stored(f"whatsapp:{client_id}")
            if not stored or not stored.get("access_token"):
                raise HTTPException(
                    status_code=400,
                    detail="WhatsApp not connected for this client",
                )
            api_key = stored["access_token"]
            sandbox = settings.env == "development"
            base = (
                "https://waba-sandbox.360dialog.io"
                if sandbox
                else "https://waba.360dialog.io"
            )
            # Use per-client URL
            webhook_url = f"{settings.backend_url}/webhooks/whatsapp/{client_id}"

            async with httpx.AsyncClient(timeout=10) as hclient:
                r = await hclient.post(
                    f"{base}/v1/configs/webhook",
                    headers={
                        "D360-API-KEY": api_key,
                        "Content-Type": "application/json",
                    },
                    json={"url": webhook_url},
                )
            result = r.json()
            webhook_ok = r.status_code == 200

            from config.channel_registry import register_channel_token
            register_channel_token(
                channel="whatsapp",
                token=api_key,
                client_id=client_id,
                webhook_url=webhook_url,
                webhook_verified=webhook_ok,
            )

            _store_provider_meta(client_id, "whatsapp", {
                "webhook_url": webhook_url,
                "webhook_set": webhook_ok,
            })

            logger.info(
                "Admin re-registered WhatsApp webhook client=%s url=%s ok=%s",
                client_id, webhook_url, webhook_ok,
            )

            return {
                "status": "webhook_set",
                "provider": "whatsapp",
                "webhook_url": webhook_url,
                "sandbox": sandbox,
                "detail": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    if provider == "twilio_whatsapp":
        try:
            from integrations.token_manager import _get_stored
            stored = _get_stored(f"twilio_whatsapp:{client_id}")
            if not stored or not stored.get("access_token"):
                raise HTTPException(
                    status_code=400,
                    detail="Twilio WhatsApp not connected for this client",
                )
            webhook_url = f"{settings.backend_url}/webhooks/twilio/{client_id}"
            from config.channel_registry import register_channel_token
            register_channel_token(
                channel="twilio_whatsapp",
                token=client_id,
                client_id=client_id,
                webhook_url=webhook_url,
                webhook_verified=True,
            )
            _store_provider_meta(client_id, "twilio_whatsapp", {
                "webhook_url": webhook_url,
                "webhook_set": True,
            })
            logger.info(
                "Admin re-registered Twilio WhatsApp webhook client=%s url=%s",
                client_id, webhook_url,
            )
            return {
                "status": "webhook_set",
                "provider": "twilio_whatsapp",
                "webhook_url": webhook_url,
                "note": "Set this URL in your Twilio console under WhatsApp Sandbox / Phone Number configuration.",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=400, detail=f"Auto webhook setup not supported for {provider}")


@router.delete("/disconnect/{provider}")
def disconnect(provider: str, user: dict = Depends(get_current_user)):
    """Execute disconnect."""
    if provider not in ALL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    client_id = user.get("client_id") or user["id"]

    if provider in {"telegram", "whatsapp", "twilio_whatsapp", "email"}:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT token
                    FROM channel_tokens
                    WHERE channel = %s AND client_id = %s
                    """,
                    (provider, client_id),
                )
                row = cur.fetchone()
                cur.execute(
                    """
                    DELETE FROM channel_tokens
                    WHERE channel = %s AND client_id = %s
                    """,
                    (provider, client_id),
                )
                cur.close()

            token = row[0] if row else None
            if token:
                _redis.delete(f"channel:{provider}:{token}")
            _redis.delete(f"channel:{provider}:client:{client_id}")
        except Exception as e:
            import sys
            print(f"[WARN] Failed to cleanup channel mapping for {provider}:{client_id}: {e}", file=sys.stderr)

    pipe = _redis.pipeline()
    pipe.delete(f"token:{provider}:{client_id}")
    pipe.delete(f"integration:meta:{client_id}:{provider}")
    pipe.delete(f"integration:status:{client_id}:{provider}")
    pipe.delete(f"cb:failures:{provider}:{client_id}")
    pipe.delete(f"cb:open:{provider}:{client_id}")
    pipe.delete(f"cb:probe_lock:{provider}:{client_id}")
    pipe.delete(f"token:fatal:{provider}:{client_id}")
    if provider == "quickbooks":
        pipe.delete(f"quickbooks:org_currency:{client_id}")
    if provider == "xero":
        pipe.delete(f"xero:org_currency:{client_id}")
    pipe.execute()
    _clear_provider_meta(client_id, provider)
    _mark_disconnected(client_id, provider)
    log_action(client_id, "integrations", f"disconnect_{provider}", provider, {"connected": False}, "success")
    logger.info("Disconnected provider=%s client=%s — all cache cleared", provider, client_id)
    return {"status": "disconnected", "provider": provider}


@router.get("/webhook-urls")
def webhook_urls(user: dict = Depends(get_current_user)):
    """Execute webhook urls."""
    return {
        "webhook_urls": {
            "whatsapp": f"{settings.backend_url}/webhooks/whatsapp",
            "telegram": f"{settings.backend_url}/webhooks/telegram",
            "twilio_whatsapp": f"{settings.backend_url}/webhooks/twilio",
            "email": f"{settings.backend_url}/webhooks/email",
        },
        "note": "Configure these URLs in your channel provider dashboard.",
    }


@router.get("/admin/integrations/{client_id}")
def admin_get_integrations(client_id: str, admin: dict = Depends(require_admin)):
    """Execute admin get integrations."""
    result = []
    for provider, cfg in ALL_PROVIDERS.items():
        status = _get_status(client_id, provider)
        meta_raw = _redis.get(f"integration:meta:{client_id}:{provider}")
        result.append({
            "provider": provider,
            "label": cfg["label"],
            "category": cfg["category"],
            "auth_type": cfg["auth_type"],
            "connected": status.get("connected", False),
            "connected_at": status.get("connected_at"),
            "meta": json.loads(meta_raw) if meta_raw else {},  # type: ignore
        })
    return {"client_id": client_id, "integrations": result}


@router.get("/integrations/paypal/webhook-url")
def get_paypal_webhook_url(user: dict = Depends(get_current_user)):
    """Return paypal webhook url."""
    client_id = user.get("client_id") or user["id"]
    return {
        "webhook_url": f"{settings.backend_url}/webhooks/paypal/{client_id}",
    }


@router.delete("/admin/integrations/{client_id}/{provider}")
def admin_disconnect(client_id: str, provider: str, admin: dict = Depends(require_admin)):
    """Execute admin disconnect."""
    if provider not in ALL_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")

    pipe = _redis.pipeline()
    pipe.delete(f"token:{provider}:{client_id}")
    pipe.delete(f"integration:meta:{client_id}:{provider}")
    pipe.delete(f"integration:status:{client_id}:{provider}")
    pipe.delete(f"cb:failures:{provider}:{client_id}")
    pipe.delete(f"cb:open:{provider}:{client_id}")
    pipe.delete(f"cb:probe_lock:{provider}:{client_id}")
    pipe.delete(f"token:fatal:{provider}:{client_id}")
    if provider == "quickbooks":
        pipe.delete(f"quickbooks:org_currency:{client_id}")
    if provider == "xero":
        pipe.delete(f"xero:org_currency:{client_id}")
    pipe.execute()

    _clear_provider_meta(client_id, provider)
    _mark_disconnected(client_id, provider)
    log_action(client_id, "integrations", f"admin_disconnect_{provider}", provider, {}, "success")
    logger.info("Admin disconnected provider=%s client=%s — all cache cleared", provider, client_id)
    return {"status": "disconnected", "provider": provider, "client_id": client_id}


@router.get("/admin/integrations/{client_id}/webhook-urls")
def admin_webhook_urls(client_id: str, admin: dict = Depends(require_admin)):
    """Execute admin webhook urls."""
    return {
        "client_id": client_id,
        "webhook_urls": {
            "whatsapp": f"{settings.backend_url}/webhooks/whatsapp",
            "telegram": f"{settings.backend_url}/webhooks/telegram",
            "twilio_whatsapp": f"{settings.backend_url}/webhooks/twilio/{client_id}",
            "email": f"{settings.backend_url}/webhooks/email",
        },
        "note": "Share these with the client for channel setup."
    }


@router.post("/stripe/webhook-secret")
def save_stripe_webhook_secret(
    body: StripeWebhookRequest,
    user: dict = Depends(get_current_user)
):
    """Execute save stripe webhook secret."""
    client_id = user.get("client_id") or user["id"]
    _store_provider_meta(client_id, "stripe", {
        "webhook_secret": encrypt_secret(body.webhook_secret),
    })
    return {"status": "saved"}


@router.get("/stripe/webhook-url")
def get_stripe_webhook_url(user: dict = Depends(get_current_user)):
    """Return stripe webhook url."""
    client_id = user.get("client_id") or user["id"]
    return {
        "webhook_url": f"{settings.backend_url}/webhooks/stripe/{client_id}",
        "instructions": "Add this URL in your Stripe dashboard → Webhooks → Add endpoint. Select events: payment_intent.succeeded, invoice.paid, invoice.payment_failed. Copy the signing secret and paste it back here."
    }

@router.post("/admin/integrations/{client_id}/reset-breaker/{provider}")
def admin_reset_breaker(
    client_id: str,
    provider: str,
    admin: dict = Depends(require_admin),
):
    """Execute admin reset breaker."""
    if provider not in ALL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    service = f"{provider}:{client_id}"
    CircuitBreaker(service).reset()
    log_action(client_id, "integrations", f"reset_breaker_{provider}", provider, {}, "success")
    return {"status": "breaker_reset", "provider": provider, "client_id": client_id}


async def _exchange_code(provider: str, code: str) -> dict:
    """Execute exchange code."""
    cfg = OAUTH_PROVIDERS[provider]
    redirect_uri = get_redirect_uri(provider)
    if provider in ("xero", "quickbooks", "paypal"):
        creds = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
        headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"}
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    else:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(cfg["token_url"], headers=headers, data=data)
        response.raise_for_status()
        return response.json()


async def _fetch_xero_tenant(access_token: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.xero.com/connections",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            connections = r.json()
            logger.info("Xero connections response: %s", connections)
            if connections:
                tenant_id = connections[0]["tenantId"]
                logger.info("Xero tenant_id fetched: %s", tenant_id)
                return tenant_id
            logger.warning("Xero connections returned empty list")
    except Exception as e:
        logger.error("_fetch_xero_tenant failed: %s", e)
    return None


async def _fetch_telegram_bot_info(token: str) -> dict:
    """Retrieve telegram bot info."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        r.raise_for_status()
        return r.json().get("result", {})


async def _validate_apikey(provider: str, api_key: str, cfg: dict):
    """Validate apikey."""
    validate_url = cfg.get("validate_url")
    if not validate_url:
        if provider == "telegram":
            await _fetch_telegram_bot_info(api_key)
        return
    prefix = cfg.get("validate_prefix", "Bearer")
    header_name = cfg.get("validate_header", "Authorization")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(validate_url, headers={header_name: f"{prefix} {api_key}"})
        if r.status_code == 401:
            raise HTTPException(status_code=400, detail=f"Invalid {provider} API key")
        r.raise_for_status()


async def _register_ms_subscription(client_id: str, access_token: str):
    """Execute register ms subscription."""
    subscriptions = [
        {
            "changeType": "created,updated",
            "notificationUrl": f"{settings.backend_url}/webhooks/microsoft/{client_id}",
            "resource": "/me/mailFolders('Inbox')/messages",
            "expirationDateTime": "2026-12-31T00:00:00Z",
            "clientState": client_id,
        },
        {
            "changeType": "created,updated,deleted",
            "notificationUrl": f"{settings.backend_url}/webhooks/microsoft/{client_id}",
            "resource": "/me/events",
            "expirationDateTime": "2026-12-31T00:00:00Z",
            "clientState": client_id,
        },
    ]
    async with httpx.AsyncClient(timeout=10) as client:
        for sub in subscriptions:
            try:
                await client.post(
                    "https://graph.microsoft.com/v1.0/subscriptions",
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    json=sub,
                )
            except Exception as e:
                logger.warning("MS subscription registration failed: %s", e)


async def _register_google_watches(client_id: str, access_token: str):
    """Execute register google watches."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    webhook_url = f"{settings.backend_url}/webhooks/google/{client_id}"
    watches = [
        {
            "url": "https://www.googleapis.com/calendar/v3/calendars/primary/events/watch",
            "body": {
                "id": f"calendar-{client_id}",
                "type": "web_hook",
                "address": webhook_url,
            }
        },
        {
            "url": "https://www.googleapis.com/drive/v3/changes/watch",
            "body": {
                "id": f"drive-{client_id}",
                "type": "web_hook",
                "address": webhook_url,
                "pageToken": "1",
            }
        },
    ]
    async with httpx.AsyncClient(timeout=10) as client:
        for watch in watches:
            try:
                await client.post(watch["url"], headers=headers, json=watch["body"])
            except Exception as e:
                logger.warning("Google watch registration failed: %s", e)


async def _register_paypal_webhook(client_id: str, access_token: str) -> str:
    """Execute register paypal webhook."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api-m.paypal.com/v1/notifications/webhooks",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": f"{settings.backend_url}/webhooks/paypal/{client_id}",
                    "event_types": [
                        {"name": "PAYMENT.CAPTURE.COMPLETED"},
                        {"name": "INVOICING.INVOICE.PAID"},
                        {"name": "PAYMENT.CAPTURE.DENIED"},
                    ]
                }
            )
            data = r.json()
            return data.get("id", "")
    except Exception as e:
        logger.error("PayPal webhook registration failed: %s", e)
        return ""


@router.post("/admin/integrations/{client_id}/re-register-channels")
async def admin_re_register_channels(
    client_id: str,
    admin: dict = Depends(require_admin),
):
    """Execute admin re register channels."""
    from config.channel_registry import register_channel_token
    from config.db_pool import get_conn

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT channel, token, webhook_url, webhook_verified
                FROM channel_tokens
                WHERE client_id = %s
                """,
                (client_id,),
            )
            rows = cur.fetchall()
            cur.close()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"No channel tokens found for client_id={client_id}. "
                       "Use setup-webhook to register first.",
            )

        restored = []
        for channel, token, webhook_url, webhook_verified in rows:
            register_channel_token(
                channel=channel,
                token=token,
                client_id=client_id,
                webhook_url=webhook_url or "",
                webhook_verified=bool(webhook_verified),
            )
            restored.append({"channel": channel, "webhook_url": webhook_url})

        log_action(
            client_id,
            "integrations",
            "re_register_channels",
            "channel_registry",
            {"channels": [r["channel"] for r in restored]},
            "success",
        )
        return {"status": "re_registered", "client_id": client_id, "channels": restored}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def admin_re_register_all_channels(admin: dict = Depends(require_admin)):
    """Execute admin re register all channels."""
    from config.channel_registry import restore_channel_tokens_to_redis

    count = restore_channel_tokens_to_redis()
    return {"status": "ok", "tokens_restored": count}