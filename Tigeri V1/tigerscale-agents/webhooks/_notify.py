"""Contain notify backend logic."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

def notify_client(client_id: str, message: str) -> None:
    """Execute notify client."""
    try:
        from core.alerting import send_client_telegram_alert
        send_client_telegram_alert(client_id, message)
    except Exception as exc:
        logger.error("notify_client failed client=%s: %s", client_id, exc)