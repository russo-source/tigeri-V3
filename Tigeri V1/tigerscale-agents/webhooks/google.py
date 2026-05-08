"""Contain google backend logic."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from security.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/google/{client_id}")
async def google_webhook(client_id: str, request: Request) -> Response:
    """Execute google webhook."""
    resource_state = request.headers.get("X-Goog-Resource-State", "")

    if resource_state == "sync":
        return Response(status_code=200)

    resource_uri = request.headers.get("X-Goog-Resource-Uri", "")
    channel_id   = request.headers.get("X-Goog-Channel-Id", "")

    try:
        if "gmail" in resource_uri or "mail" in channel_id:
            _sync_gmail(client_id, resource_uri)
        elif "calendar" in resource_uri or "calendar" in channel_id:
            _sync_calendar(client_id, resource_uri)
        elif "drive" in resource_uri or "drive" in channel_id:
            _sync_drive(client_id, resource_uri)
        else:
            logger.debug("Google webhook ignored — unknown resource client=%s uri=%s",
                         client_id, resource_uri)
    except Exception as exc:
        logger.error("Google webhook handler failed client=%s: %s", client_id, exc, exc_info=True)

    return Response(status_code=200)


def _sync_gmail(client_id: str, uri: str) -> None:
    """Synchronize gmail."""
    log_action(client_id, "google_sync", "gmail_received", uri, {}, "success")


def _sync_calendar(client_id: str, uri: str) -> None:
    """Synchronize calendar."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE documents SET status = 'updated' "
                "WHERE client_id = %s AND doc_type = 'calendar_event'",
                (client_id,),
            )
            cur.close()
        log_action(client_id, "google_sync", "calendar_updated", uri, {}, "success")
    except Exception as exc:
        logger.error("google _sync_calendar failed client=%s: %s", client_id, exc)


def _sync_drive(client_id: str, uri: str) -> None:
    """Synchronize drive."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE documents SET status = 'updated' "
                "WHERE client_id = %s AND doc_type = 'drive_file'",
                (client_id,),
            )
            cur.close()
        log_action(client_id, "google_sync", "drive_updated", uri, {}, "success")
    except Exception as exc:
        logger.error("google _sync_drive failed client=%s: %s", client_id, exc)