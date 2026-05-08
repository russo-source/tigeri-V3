"""Contain channel registry backend logic."""
import sys
from typing import Optional, cast

import redis

from config.settings import settings

_redis = redis.from_url(settings.redis_url, decode_responses=True)

_CHANNEL_KEY_TTL: Optional[int] = None

def register_channel_token(
    channel: str,
    token: str,
    client_id: str,
    webhook_url: str = "",
    webhook_verified: bool = False,
) -> None:
    """Execute register channel token."""
    _write_redis_pair(channel, token, client_id)
    _persist_channel_token(channel, token, client_id, webhook_url, webhook_verified)


def resolve_client_id(channel: str, token: str) -> Optional[str]:
    """Resolve client id."""
    result = cast(Optional[str], _redis.get(f"channel:{channel}:{token}"))
    if result:
        return result
    return _load_channel_token_by_token(channel, token)


def resolve_token_by_client(channel: str, client_id: str) -> Optional[str]:
    """Resolve token by client."""
    result = cast(Optional[str], _redis.get(f"channel:{channel}:client:{client_id}"))
    if result:
        return result
    return _load_token_by_client(channel, client_id)


def restore_channel_tokens_to_redis() -> int:
    """Execute restore channel tokens to redis."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT channel, token, client_id FROM channel_tokens")
            rows = cur.fetchall()
            cur.close()

        if not rows:
            print("[STARTUP] channel_registry: no channel tokens found in DB", flush=True)
            return 0

        pipe = _redis.pipeline(transaction=False)
        for channel, token, client_id in rows:
            _pipeline_write_pair(pipe, channel, token, client_id)
        pipe.execute()

        print(f"[STARTUP] channel_registry: restored {len(rows)} channel token(s) to Redis", flush=True)
        return len(rows)

    except Exception as e:
        print(f"[ERROR] restore_channel_tokens_to_redis failed: {e}", file=sys.stderr, flush=True)
        return 0

def _write_redis_pair(channel: str, token: str, client_id: str) -> None:
    """Execute write redis pair."""
    pipe = _redis.pipeline(transaction=True)
    _pipeline_write_pair(pipe, channel, token, client_id)
    pipe.execute()


def _pipeline_write_pair(pipe, channel: str, token: str, client_id: str) -> None:
    """Execute pipeline write pair."""
    fwd_key = f"channel:{channel}:{token}"
    rev_key = f"channel:{channel}:client:{client_id}"
    if _CHANNEL_KEY_TTL:
        pipe.setex(fwd_key, _CHANNEL_KEY_TTL, client_id)
        pipe.setex(rev_key, _CHANNEL_KEY_TTL, token)
    else:
        pipe.set(fwd_key, client_id)
        pipe.set(rev_key, token)


def _persist_channel_token(
    channel: str,
    token: str,
    client_id: str,
    webhook_url: str,
    webhook_verified: bool,
) -> None:
    """Execute persist channel token."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO channel_tokens (channel, token, client_id, webhook_url, webhook_verified, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (channel, client_id)
                DO UPDATE SET
                    token             = EXCLUDED.token,
                    webhook_url       = EXCLUDED.webhook_url,
                    webhook_verified  = EXCLUDED.webhook_verified,
                    updated_at        = NOW()
                """,
                (channel, token, client_id, webhook_url, webhook_verified),
            )
            cur.close()
    except Exception as e:
        print(f"[ERROR] _persist_channel_token({channel}, {client_id}): {e}", file=sys.stderr, flush=True)


def _load_channel_token_by_token(channel: str, token: str) -> Optional[str]:
    """Load channel token by token."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT client_id FROM channel_tokens WHERE channel = %s AND token = %s",
                (channel, token),
            )
            row = cur.fetchone()
            cur.close()
        if row:
            client_id = row[0]
            _write_redis_pair(channel, token, client_id)
            return client_id
    except Exception as e:
        print(f"[ERROR] _load_channel_token_by_token({channel}): {e}", file=sys.stderr, flush=True)
    return None


def _load_token_by_client(channel: str, client_id: str) -> Optional[str]:
    """Load token by client."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT token FROM channel_tokens WHERE channel = %s AND client_id = %s",
                (channel, client_id),
            )
            row = cur.fetchone()
            cur.close()
        if row:
            token = row[0]
            _write_redis_pair(channel, token, client_id)
            return token
    except Exception as e:
        print(f"[ERROR] _load_token_by_client({channel}, {client_id}): {e}", file=sys.stderr, flush=True)
    return None