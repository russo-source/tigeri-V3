"""Contain microsoft backend logic."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse, Response

from security.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/microsoft/{client_id}")
async def microsoft_webhook(
    client_id: str,
    request: Request,
    validationToken: str = Query(default=None),
) -> Response:
    """Execute microsoft webhook."""
    if validationToken:
        return PlainTextResponse(content=validationToken, status_code=200)

    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, Exception):
        return Response(status_code=400)

    for notification in payload.get("value", []):
        resource    = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        try:
            if "messages" in resource:
                _sync_email(client_id, resource)
            elif "events" in resource:
                _sync_calendar(client_id, resource)
            elif "drive" in resource:
                _sync_drive(client_id, resource)
        except Exception as exc:
            logger.error("MS webhook handler failed client=%s resource=%s: %s",
                         client_id, resource, exc, exc_info=True)

    return Response(status_code=202)


def _sync_email(client_id: str, resource: str) -> None:
    """Synchronize email."""
    log_action(client_id, "ms_sync", "email_received", resource, {}, "success")


def _sync_calendar(client_id: str, resource: str) -> None:
    """Synchronize calendar."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE documents SET status = 'updated' "
                "WHERE client_id = %s AND doc_type = 'calendar_event' AND filename = %s",
                (client_id, resource),
            )
            cur.close()
        log_action(client_id, "ms_sync", "calendar_updated", resource, {}, "success")
    except Exception as exc:
        logger.error("ms _sync_calendar failed client=%s: %s", client_id, exc)


def _sync_drive(client_id: str, resource: str) -> None:
    """Synchronize drive."""
    log_action(client_id, "ms_sync", "drive_updated", resource, {}, "success")