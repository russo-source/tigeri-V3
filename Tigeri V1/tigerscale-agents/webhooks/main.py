"""Contain main backend logic."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from webhooks.whatsapp import router as whatsapp_router
from webhooks.twilio_whatsapp import router as twilio_whatsapp_router
from webhooks.telegram import router as telegram_router
from webhooks.email import router as email_router
from webhooks.health import router as health_router
from webhooks.clients import router as clients_router
from webhooks.subscriptions import router as subscription_router
from webhooks.onboarding import router as onboarding_router
from webhooks.channels import router as channels_router
from webhooks.auth import router as auth_router
from webhooks.dashboard import router as dashboard_router
from webhooks.integrations import router as integrations_router
from webhooks.xero import router as xero_router
from webhooks.quickbooks import router as quickbooks_router
from webhooks.stripe import router as stripe_router
from webhooks.microsoft import router as microsoft_router
from webhooks.google import router as google_router
from webhooks.paypal import router as paypal_router
from webhooks.log_stream import router as log_stream_router
from webhooks.admin_init import router as admin_init_router
from webhooks.approval import router as approval_router
from webhooks.approver_config import router as approver_config_router
from webhooks.financial_config import router as financial_config_router
from core.orchestrator import register_agent
from agents.a01_invoice.agent import InvoiceAgent
from agents.a02_expense.agent import ExpenseAgent
from agents.a03_admin.agent   import AdminAgent
from agents.a04_payment.agent import PaymentAgent
from config.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Execute lifespan."""
    try:
        from migrations.runner import run_migrations
        run_migrations()
        logger.info("DB migrations complete")
    except Exception as exc:
        logger.critical("DB migration failed: %s", exc, exc_info=True)

    try:
        import time
        import redis as redis_lib
        from config.db_pool import get_conn
        from integrations.token_manager import _store_token

        _redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT ci.client_id, ci.provider, ci.meta,
                       EXTRACT(EPOCH FROM ci.refresh_token_expires_at) AS rt_expires_at
                FROM client_integrations ci
                WHERE ci.connected = TRUE
            """)
            rows = cur.fetchall()
            cur.close()

        restored = skipped = 0
        for client_id, provider, meta, rt_expires_at in rows:
            try:
                key  = f"token:{provider}:{client_id}"
                meta = meta or {}
                if _redis.exists(key):
                    skipped += 1
                    continue

                access_token = meta.get("access_token", "")
                refresh_token = meta.get("refresh_token", "")
                expires_at = meta.get("expires_at", 0)
                remaining = max(int(float(expires_at) - time.time()), 0) if expires_at else 0

                if access_token:
                    rt_remaining = (
                        int(float(rt_expires_at) - time.time()) if rt_expires_at else None
                    )
                    _store_token(
                        service=f"{provider}:{client_id}",
                        access_token=access_token,
                        expires_in=remaining or 60,
                        refresh_token=refresh_token,
                        refresh_token_expires_in=rt_remaining,
                    )
                    restored += 1
                    logger.info("OAuth restored: %s:%s", provider, client_id)
                else:
                    skipped += 1
                    logger.debug("OAuth skipped (no token): %s:%s", provider, client_id)
            except Exception as exc:
                logger.error("OAuth restore failed %s:%s: %s", provider, client_id, exc)

        logger.info("OAuth restore complete: %d restored, %d skipped", restored, skipped)

    except Exception as exc:
        logger.critical("OAuth token restoration failed entirely: %s", exc, exc_info=True)

    try:
        from config.channel_registry import restore_channel_tokens_to_redis
        count = restore_channel_tokens_to_redis()
        if count == 0:
            logger.warning(
                "No channel tokens found in DB. "
                "If Telegram/WhatsApp were previously connected, "
                "run POST /api/v1/integrations/admin/{client_id}/setup-webhook/telegram to re-register."
            )
        else:
            logger.info("Channel tokens restored: %d", count)
    except Exception as exc:
        logger.critical("Channel token restoration failed: %s", exc, exc_info=True)

    yield

    logger.info("App shutting down")


app = FastAPI(lifespan=lifespan)

_CORS_ORIGINS = getattr(settings, "cors_origins", None) or [
    "https://www.tigeri.ai",
    "https://api.tigeri.ai",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

register_agent("a01_invoice", InvoiceAgent)
register_agent("a02_expense", ExpenseAgent)
register_agent("a03_admin",   AdminAgent)
register_agent("a04_payment", PaymentAgent)

app.include_router(whatsapp_router)
app.include_router(twilio_whatsapp_router)
app.include_router(telegram_router)
app.include_router(email_router)
app.include_router(health_router)
app.include_router(clients_router)
app.include_router(subscription_router)
app.include_router(channels_router)
app.include_router(onboarding_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(integrations_router)
app.include_router(xero_router)
app.include_router(quickbooks_router)
app.include_router(stripe_router)
app.include_router(microsoft_router)
app.include_router(google_router)
app.include_router(paypal_router)
app.include_router(log_stream_router)
app.include_router(admin_init_router)
app.include_router(approval_router)
app.include_router(approver_config_router)
app.include_router(financial_config_router)

@app.get("/media/{token}")
def serve_temp_media(token: str):
    """Serve a short-lived file stored in Redis for Twilio MediaUrl delivery."""
    import base64
    import redis as _redis_lib
    from fastapi.responses import Response as _Resp
    r = _redis_lib.from_url(settings.redis_url, decode_responses=False)
    raw = r.get(f"media:tmp:{token}")
    if not raw:
        from fastapi import HTTPException as _HTTPEx
        raise _HTTPEx(status_code=404, detail="Media not found or expired")
    # stored as b"<mime>\n<b64data>"
    sep = raw.index(b"\n")
    mime = raw[:sep].decode()
    data = base64.b64decode(raw[sep + 1:])
    return _Resp(content=data, media_type=mime)


@app.get("/health")
def health() -> dict:
    """Execute health."""
    return {"status": "ok"}


@app.get("/agents")
def list_agents() -> dict:
    """List agents."""
    from core.orchestrator import AGENT_REGISTRY
    return {"agents": list(AGENT_REGISTRY.keys()), "count": len(AGENT_REGISTRY)}