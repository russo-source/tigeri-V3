"""Contain audit backend logic."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis
from config.settings import settings
from config.db_pool import get_conn
logger = logging.getLogger(__name__)

_redis = redis.from_url(settings.redis_url, decode_responses=True)

# Constant for audit fallback key.
AUDIT_FALLBACK_KEY = "audit:fallback"
# Constant for audit poison key.
AUDIT_POISON_KEY = "audit:fallback:poison"
# Constant for drain batch size.
DRAIN_BATCH_SIZE = 500   # max items per drain run
# Constant for poison maximum size.
POISON_MAX_SIZE = 1000  # alert poison queue exceeds


def log_action(
    client_id: str,
    agent_name: str,
    intent: str,
    input_text: str,
    output: dict,
    status: str,
    error_ref: Optional[str] = None,
    message: Optional[str] = None,
) -> str:
    """Execute log action."""
    input_hash = _hash(input_text)
    output_hash = _hash(json.dumps(output, default=str))
    ref = f"LOG-{input_hash[:8]}"

    row = (
        client_id,agent_name,intent,
        input_hash,output_hash,status,
        error_ref or ref,
        message or f"{agent_name} processed {intent}",
        datetime.now(timezone.utc),
    )

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_logs
                  (client_id, agent_name, intent, input_hash, output_hash,
                   status, error_ref, message, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                row,
            )
            cur.close()
    except Exception as e:
        logger.critical("Audit DB write failed — Redis fallback: %s", e)
        _redis.rpush(AUDIT_FALLBACK_KEY, json.dumps({
            "client_id": client_id,
            "agent_name": agent_name,
            "intent": intent,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "status": status,
            "error_ref": error_ref or ref,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

    return ref


def log_webhook(
    client_id: str,
    channel: str,
    endpoint: str,
    status: int,
    error_ref: Optional[str] = None,
) -> None:
    """Execute log webhook."""
    row = (
        client_id,f"webhook:{channel}",endpoint,
        "webhook",str(status), str(status),
        error_ref, datetime.now(timezone.utc),
    )
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_logs
                  (client_id, agent_name, intent, input_hash, output_hash,
                   status, error_ref, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                row,
            )
            cur.close()
    except Exception as e:
        logger.critical("Webhook audit DB write failed — Redis fallback: %s", e)
        _redis.rpush(AUDIT_FALLBACK_KEY, json.dumps({
            "client_id":   client_id,
            "agent_name":  f"webhook:{channel}",
            "intent":      endpoint,
            "input_hash":  "webhook",
            "output_hash": str(status),
            "status":      str(status),
            "error_ref":   error_ref,
            "message":     None,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }))


def drain_fallback() -> int:
    """Execute drain fallback."""
    drained = 0
    poison_count = int(_redis.llen(AUDIT_POISON_KEY) or 0) # type: ignore

    if poison_count > POISON_MAX_SIZE:
        logger.error(
            "Audit poison queue has %d items — investigate immediately",
            poison_count,
        )
        try:
            from core.alerting import send_telegram_alert
            send_telegram_alert(
                f"[AUDIT] Poison queue has {poison_count} items — DB may be rejecting audit rows"
            )
        except Exception:
            pass

    for _ in range(DRAIN_BATCH_SIZE):
        item = _redis.lpop(AUDIT_FALLBACK_KEY)
        if not item:
            break
        try:
            data = json.loads(item)  # type: ignore
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO audit_logs
                      (client_id, agent_name, intent, input_hash, output_hash,
                       status, error_ref, message, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        data.get("client_id"),
                        data.get("agent_name"),
                        data.get("intent"),
                        data.get("input_hash"),
                        data.get("output_hash"),
                        data.get("status"),
                        data.get("error_ref"),
                        data.get("message"),
                        data.get("created_at"),
                    ),
                )
                cur.close()
            drained += 1
        except Exception as e:
            logger.error("Drain failed for item — moving to poison queue: %s", e)
            _redis.rpush(AUDIT_POISON_KEY, item)  # type: ignore

    return drained


def _hash(text: str) -> str:
    """Execute hash."""
    return hashlib.sha256(text.encode()).hexdigest()