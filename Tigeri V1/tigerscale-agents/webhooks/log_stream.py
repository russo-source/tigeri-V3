"""Contain log stream backend logic."""
from __future__ import annotations
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from auth.deps import get_current_user
from config.db_pool import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()
_MAX_CONNS = 50
_active = 0


@router.get("/client/logs/stream")
async def stream_logs(user: dict = Depends(get_current_user)) -> StreamingResponse:
    """Execute stream logs."""
    global _active
    if _active >= _MAX_CONNS:
        raise HTTPException(status_code=503, detail="Too many active log streams. Try again later.")

    client_id = user["client_id"]

    async def event_generator():
        """Execute event generator."""
        global _active
        _active += 1
        last_seen = None
        try:
            while True:
                try:
                    with get_conn() as conn:
                        cur = conn.cursor()
                        if last_seen:
                            cur.execute("""
                                SELECT agent_name, intent, status, message, error_ref, created_at
                                FROM audit_logs
                                WHERE client_id = %s AND created_at > %s
                                ORDER BY created_at ASC
                            """, (client_id, last_seen))
                        else:
                            cur.execute("""
                                SELECT agent_name, intent, status, message, error_ref, created_at
                                FROM audit_logs
                                WHERE client_id = %s
                                ORDER BY created_at DESC
                                LIMIT 50
                            """, (client_id,))
                        rows = cur.fetchall()
                        cur.close()

                    if rows:
                        last_seen = max(r[5] for r in rows)
                        logs = [
                            {
                                "agent": r[0],
                                "intent": r[1],
                                "status": r[2],
                                "message": r[3],
                                "ref": r[4],
                                "at": r[5].isoformat() if r[5] else None,
                            }
                            for r in rows
                        ]
                        yield f"data: {json.dumps(logs)}\n\n"
                    else:
                        yield ": ping\n\n"

                except Exception as exc:
                    logger.error("log_stream error client=%s: %s", client_id, exc)
                    yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                    await asyncio.sleep(5)
                    continue

                await asyncio.sleep(2)
        finally:
            _active -= 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )