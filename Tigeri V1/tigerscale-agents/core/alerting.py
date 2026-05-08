"""Contain alerting backend logic."""
from __future__ import annotations

import logging
 
import httpx
import redis as redis_lib
 
from config.settings import settings
 
logger = logging.getLogger(__name__)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

def _build_approval_email_body(
    action: str,
    data: dict,
    approve_url: str,
    reject_url: str,
    ttl_minutes: int,
) -> str:
    """Build approval email body."""
    currency = data.get("currency", "USD")
    amount   = data.get("amount", "")
    payer    = data.get("payer", "unknown")
    ref      = data.get("payment_ref") or "N/A"
 
    _ACTION_LABELS = {
        "refund":          "Refund",
        "capture_payment": "Capture Payment",
        "cancel_payment":  "Cancel Payment",
        "handle_dispute":  "Dispute Action",
    }
    label = _ACTION_LABELS.get(action, action.replace("_", " ").title())
 
    return f"""
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  max-width:520px;margin:0 auto;padding:32px 16px;color:#1a1a1a;">
 
  <h2 style="margin:0 0 4px;">Approval Required</h2>
  <p style="margin:0 0 24px;color:#666;">Action needs your sign-off.</p>
 
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr><td style="padding:8px 0;color:#666;width:120px;">Action</td>
        <td style="padding:8px 0;font-weight:600;">{label}</td></tr>
    <tr><td style="padding:8px 0;color:#666;">Payer</td>
        <td style="padding:8px 0;">{payer}</td></tr>
    <tr><td style="padding:8px 0;color:#666;">Amount</td>
        <td style="padding:8px 0;">{currency} {amount}</td></tr>
    <tr><td style="padding:8px 0;color:#666;">Reference</td>
        <td style="padding:8px 0;">{ref}</td></tr>
    <tr><td style="padding:8px 0;color:#666;">Expires</td>
        <td style="padding:8px 0;">{ttl_minutes} minutes</td></tr>
  </table>
 
  <div style="display:flex;gap:12px;margin-bottom:24px;">
    <a href="{approve_url}"
       style="display:inline-block;padding:12px 28px;background:#27ae60;color:#fff;
              text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
    Approve
    </a>
    <a href="{reject_url}"
       style="display:inline-block;padding:12px 28px;background:#e74c3c;color:#fff;
              text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
    Reject
    </a>
  </div>
 
  <p style="font-size:13px;color:#999;">
    These links expire in {ttl_minutes} minutes. If you did not expect this request,
    please reject it and contact your administrator.
  </p>
</body></html>
""".strip()


def notify_approver(
    client_id: str,
    action: str,
    data: dict,
    task_id: str,
    ttl_seconds: int = 300,
) -> bool:
    """Execute notify approver."""
    try:
        from config.client_config import get_client_config
        config = get_client_config(client_id)
    except Exception as exc:
        logger.error("notify_approver: could not load config client=%s: %s", client_id, exc)
        return False
 
    approver_chat_id   = config.get("approver_chat_id") or config.get("approve_chat_id")
    approve_email      = config.get("approve_email")
    approver_whatsapp  = config.get("approver_whatsapp")
 
    if not any([approver_chat_id, approve_email, approver_whatsapp]):
        logger.warning("notify_approver: no approver channels configured client=%s", client_id)
        return False
 
    _ACTION_LABELS = {
        "refund":          "Refund",
        "capture_payment": "Capture Payment",
        "cancel_payment":  "Cancel Payment",
        "handle_dispute":  "Dispute Action",
    }
    label    = _ACTION_LABELS.get(action, action.replace("_", " ").title())
    currency = data.get("currency", "USD")
    ttl_min  = ttl_seconds // 60
 
    succeeded = False
 
    if approver_chat_id:
        tg_sent = _notify_via_telegram(
            client_id=client_id,
            approver_chat_id=str(approver_chat_id),
            label=label,
            data=data,
            task_id=task_id,
            currency=currency,
            ttl_min=ttl_min,
        )
        if tg_sent:
            succeeded = True
        else:
            logger.warning(
                "notify_approver: Telegram failed client=%s task=%s", client_id, task_id
            )
 
    if approve_email:
        email_sent = _notify_via_email(
            client_id=client_id,
            approve_email=approve_email,
            action=action,
            label=label,
            data=data,
            task_id=task_id,
            ttl_seconds=ttl_seconds,
            ttl_min=ttl_min,
        )
        if email_sent:
            succeeded = True
        else:
            logger.warning(
                "notify_approver: Email failed client=%s task=%s", client_id, task_id
            )
 
    if approver_whatsapp:
        wa_sent = _notify_via_whatsapp(
            client_id=client_id,
            approver_whatsapp=str(approver_whatsapp),
            label=label,
            data=data,
            currency=currency,
            ttl_min=ttl_min,
            has_email=bool(approve_email),
        )
        if wa_sent:
            succeeded = True
        else:
            logger.warning(
                "notify_approver: WhatsApp failed client=%s task=%s", client_id, task_id
            )
 
    return succeeded


def notify_mismatch(
    client_id: str,
    data: dict,
    reason: str = "Payment could not be matched to an invoice",
) -> None:
    """Execute notify mismatch."""
    try:
        from config.client_config import get_client_config
        config         = get_client_config(client_id)
        approver_email = config.get("approve_email")
        approver_chat_id = (
            config.get("approver_chat_id") or config.get("approve_chat_id")
        )
 
        currency = data.get("currency", "USD")
        user_message = (
            f"A payment of {currency} {data.get('amount')} "
            f"from {data.get('payer', 'unknown')} requires manual review.\n"
            f"Reference: {data.get('payment_ref') or 'N/A'}\n"
            f"Reason: {reason}"
        )
 
        notified = False
 
        if approver_email:
            try:
                from integrations.email_factory import get_email_from_config
                email = get_email_from_config(client_id)
                email.send(
                    recipient=approver_email,
                    subject=f"Payment Review Required — {data.get('payment_ref', 'N/A')}",
                    body=user_message,
                )
                notified = True
            except Exception as exc:
                logger.error(
                    "notify_mismatch email failed client=%s: %s", client_id, exc
                )
 
        if approver_chat_id:
            try:
                from integrations.token_manager import _get_stored
                stored = _get_stored(f"telegram:{client_id}")
                if stored and stored.get("access_token"):
                    import httpx as _httpx
                    bot_token = stored["access_token"]
                    _httpx.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": str(approver_chat_id),
                            "text": f"{user_message[:4000]}",
                        },
                        timeout=5,
                    )
                    notified = True
            except Exception as exc:
                logger.error(
                    "notify_mismatch telegram failed client=%s: %s", client_id, exc
                )
 
        if not notified:
            logger.warning(
                "notify_mismatch: no approver configured client=%s — "
                "falling back to last sender",
                client_id,
            )
            from core.alerting import send_client_telegram_alert
            send_client_telegram_alert(client_id, user_message)
 
    except Exception as exc:
        logger.error("notify_mismatch failed client=%s: %s", client_id, exc)

def send_telegram_alert(
    message:   str,
    bot_token: str | None = None,
    chat_id:   str | None = None,
) -> None:
    """Send telegram alert."""
    token = bot_token or settings.telegram_bot_token
    cid   = chat_id   or settings.telegram_alert_chat_id
    if not token or not cid:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": f"[ALERT] {message[:4000]}"},
            timeout=5,
        )
    except Exception as e:
        logger.critical("Telegram ops alert failed: %s", e)


def send_ops_telegram_alert(message: str) -> None:
    """Send ops telegram alert."""
    token = settings.telegram_bot_token
    cid   = settings.telegram_alert_chat_id
    if not token or not cid:
        logger.warning("send_ops_telegram_alert: no ops bot token or chat_id configured")
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": f"🔴 {message[:4000]}"},
            timeout=5,
        )
    except Exception as e:
        logger.critical("Ops Telegram alert failed (non-fatal): %s", e)


def send_client_telegram_alert(client_id: str, message: str) -> None:
    """Send client telegram alert."""
    try:
        from integrations.token_manager import _get_stored
        stored = _get_stored(f"telegram:{client_id}")
        if not stored or not stored.get("access_token"):
            return
        chat_id = _redis.get(f"telegram:last_sender:{client_id}")
        if not chat_id:
            return
        send_telegram_alert(
            message,
            bot_token=stored["access_token"],
            chat_id=str(chat_id),
        )
    except Exception as e:
        logger.error("Client telegram alert failed client=%s: %s", client_id, e)


def send_approver_telegram_alert(
    client_id: str,
    message: str,
    buttons: list[dict] | None = None,
) -> bool:
    """Send approver telegram alert."""
    try:
        from integrations.token_manager import _get_stored
        from config.client_config import get_client_config

        stored = _get_stored(f"telegram:{client_id}")
        if not stored or not stored.get("access_token"):
            logger.warning(
                "send_approver_telegram_alert: no bot token for client=%s", client_id
            )
            return False

        config = get_client_config(client_id)
        approver_chat_id = config.get("approver_chat_id") or config.get("approve_chat_id")
        if not approver_chat_id:
            logger.warning(
                "send_approver_telegram_alert: no approver_chat_id configured client=%s",
                client_id,
            )
            return False

        bot_token = stored["access_token"]
        payload: dict = {
            "chat_id": str(approver_chat_id),
            "text":    message[:4096],
            "parse_mode": "Markdown",
        }

        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": b["label"], "callback_data": b["data"]} for b in buttons]
                ]
            }

        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        return True

    except Exception as e:
        logger.error(
            "send_approver_telegram_alert failed client=%s: %s", client_id, e
        )
        return False
    
    

def _notify_via_telegram(
    client_id: str,
    approver_chat_id: str,
    label: str,
    data: dict,
    task_id: str,
    currency: str,
    ttl_min: int,
) -> bool:
    """Execute notify via telegram."""
    try:
        from integrations.token_manager import _get_stored
        stored = _get_stored(f"telegram:{client_id}")
        if not stored or not stored.get("access_token"):
            logger.warning(
                "_notify_via_telegram: no bot token client=%s", client_id
            )
            return False
 
        bot_token = stored["access_token"]
        message = (
            f"*Approval Required*\n"
            f"Action:    {label}\n"
            f"Payer:     {data.get('payer', 'unknown')}\n"
            f"Amount:    {currency} {data.get('amount', '')}\n"
            f"Reference: {data.get('payment_ref', 'N/A')}\n"
            f"Expires:   {ttl_min} min"
        )
        payload: dict = {
            "chat_id":    approver_chat_id,
            "text":       message,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Approve", "callback_data": f"payment_approve:{task_id}"},
                    {"text": "Reject",  "callback_data": f"payment_reject:{task_id}"},
                ]]
            },
        }
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("_notify_via_telegram failed client=%s: %s", client_id, exc)
        return False
 
 
def _notify_via_email(
    client_id: str,
    approve_email: str,
    action: str,
    label: str,
    data: dict,
    task_id: str,
    ttl_seconds: int,
    ttl_min: int,
) -> bool:
    """Execute notify via email."""
    try:
        from security.approval_token import generate_approval_token
        from integrations.email_factory import get_email_from_config
 
        token = generate_approval_token(
            client_id=client_id,
            task_id=task_id,
            action=action,
            expires_in=ttl_seconds,
        )
 
        backend_url = getattr(settings, "backend_url", "").rstrip("/")
        approve_url = f"{backend_url}/webhooks/approve?token={token}&result=approved"
        reject_url  = f"{backend_url}/webhooks/approve?token={token}&result=rejected"
 
        html_body = _build_approval_email_body(
            action=action,
            data=data,
            approve_url=approve_url,
            reject_url=reject_url,
            ttl_minutes=ttl_min,
        )
 
        email = get_email_from_config(client_id)
        sent  = email.send(
            recipient=approve_email,
            subject=f"Action Required: {label} — {data.get('currency', 'USD')} {data.get('amount', '')}",
            body=html_body,
        )
        return bool(sent)
    except Exception as exc:
        logger.error("_notify_via_email failed client=%s: %s", client_id, exc)
        return False
 
 
def _notify_via_whatsapp(
    client_id: str,
    approver_whatsapp: str,
    label: str,
    data: dict,
    currency: str,
    ttl_min: int,
    has_email: bool,
) -> bool:
    """Execute notify via whatsapp."""
    try:
        from channels.whatsapp import WhatsAppChannel
        channel = WhatsAppChannel(client_id=client_id)
 
        email_note = (
            " Please check your email to approve or reject."
            if has_email
            else " Please contact your administrator to action this."
        )
 
        message = (
            f"*Approval Required*\n"
            f"Action: {label}\n"
            f"Payer: {data.get('payer', 'unknown')}\n"
            f"Amount: {currency} {data.get('amount', '')}\n"
            f"Reference: {data.get('payment_ref', 'N/A')}\n"
            f"Expires in: {ttl_min} min\n"
            f"{email_note}"
        )
        return channel.send(recipient=approver_whatsapp, message=message)
    except Exception as exc:
        logger.error("_notify_via_whatsapp failed client=%s: %s", client_id, exc)
        return False