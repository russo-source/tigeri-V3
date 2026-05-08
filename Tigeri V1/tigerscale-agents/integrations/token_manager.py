from __future__ import annotations
import base64
import json
import logging
import time
from typing import Optional
import httpx
import redis

from config.settings import settings
logger = logging.getLogger(__name__)

_redis = redis.from_url(settings.redis_url, decode_responses=True)


# How many seconds before expiry we proactively refresh.
TOKEN_BUFFER_SECONDS: int = 300

# Distributed-lock TTL / wait / poll (seconds).
REFRESH_LOCK_TTL: int = 20
REFRESH_LOCK_WAIT: int = 15
REFRESH_LOCK_POLL: float = 0.5

# How many consecutive fatal auth errors before we declare a token dead.
DEAD_TOKEN_THRESHOLD: int = 3

# TTL on the consecutive-failure counter (seconds).  Resets if the service
# recovers on its own.
DEAD_TOKEN_WINDOW: int = 600   # 10 minutes

# Dedup window for "token dead" client alerts (seconds).
DEAD_TOKEN_ALERT_TTL: int = 300

# Redis cache TTL after a successful token store (seconds).
REDIS_CACHE_TTL: int = 7_200   # 2 hours


def _token_key(service: str) -> str:
    return f"token:{service}"

def _lock_key(service: str) -> str:
    return f"token:lock:{service}"

def _fatal_counter_key(service: str) -> str:
    """Consecutive fatal-auth-error counter for dead-token detection."""
    return f"token:fatal:{service}"

def _dead_alert_key(service: str) -> str:
    return f"dead_token:alerted:{service}"


def _pg_store(
    service: str,
    access_token: str,
    expires_at: float,
    refresh_token: str,
    refresh_token_expires_at: float,
    version_increment: bool = True,
) -> int:
    """
    Upsert token into Postgres.

    Returns the new token_version so the caller can embed it in the Redis
    cache entry and detect stale overwrites.
    """
    from config.db_pool import get_conn

    parts = service.split(":", 1)
    if len(parts) != 2:
        logger.error("_pg_store: bad service key '%s'", service)
        return 0

    provider, client_id = parts

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE((meta->>'token_version')::int, 0) "
                "FROM client_integrations "
                "WHERE client_id=%s AND provider=%s",
                (client_id, provider),
            )
            row = cur.fetchone()
            current_version: int = row[0] if row else 0
            new_version = current_version + 1 if version_increment else current_version

            token_meta = {
                "access_token": access_token,
                "expires_at": expires_at,
                "refresh_token": refresh_token,
                "refresh_token_expires_at": refresh_token_expires_at,
                "token_version": new_version,
            }
            cur.execute(
                """
                INSERT INTO client_integrations
                (client_id, provider, connected, meta,
                refresh_token_expires_at, updated_at)
                VALUES (%s, %s, TRUE, %s::jsonb, to_timestamp(%s), NOW())
                ON CONFLICT (client_id, provider) DO UPDATE SET
                    meta = client_integrations.meta || %s::jsonb,
                    connected                = TRUE,
                    refresh_token_expires_at = EXCLUDED.refresh_token_expires_at,
                    updated_at               = NOW()
                """,
                (
                    client_id,
                    provider,
                    json.dumps(token_meta),
                    refresh_token_expires_at,
                    json.dumps(token_meta),
                ),
            )
            cur.close()
            return new_version
    except Exception as exc:
        logger.error("_pg_store failed for %s: %s", service, exc)
        return 0


def _pg_load(service: str) -> dict:
    """
    Load token from Postgres.  Returns {} if not found or on error.
    Does NOT touch Redis.
    """
    from config.db_pool import get_conn

    parts = service.split(":", 1)
    if len(parts) != 2:
        return {}
    provider, client_id = parts

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT meta, EXTRACT(EPOCH FROM refresh_token_expires_at)
                FROM client_integrations
                WHERE client_id=%s AND provider=%s AND connected=TRUE
                """,
                (client_id, provider),
            )
            row = cur.fetchone()
            cur.close()

        if not row or not row[0]:
            return {}

        meta: dict = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        if not meta.get("access_token"):
            return {}
        
        if not meta.get("refresh_token_expires_at") and row[1]:
            meta["refresh_token_expires_at"] = float(row[1])

        return meta

    except Exception as exc:
        logger.error("_pg_load failed for %s: %s", service, exc)
        return {}

def _cache_warm(service: str, meta: dict, version: int) -> None:
    """
    Write an encrypted snapshot into Redis.  The version is embedded so that
    stale-write detection works across workers.
    """
    from security.encryption import encrypt_secret

    try:
        payload = {
            "access_token":             encrypt_secret(meta["access_token"]),
            "refresh_token":            encrypt_secret(meta.get("refresh_token", "")) if meta.get("refresh_token") else "",
            "expires_at":               meta["expires_at"],
            "refresh_token_expires_at": meta.get("refresh_token_expires_at", time.time() + 5_184_000),
            "token_version":            version,
        }
        _redis.setex(_token_key(service), REDIS_CACHE_TTL, json.dumps(payload))
    except Exception as exc:
        logger.warning("_cache_warm failed for %s (non-fatal): %s", service, exc)


def _cache_read(service: str) -> dict:
    """
    Read and decrypt token from Redis.  Returns {} on any failure so the
    caller always falls through to Postgres.
    """
    from security.encryption import decrypt_secret

    raw = _redis.get(_token_key(service))
    if not raw:
        return {}

    try:
        data = json.loads(str(raw))

        at = data.get("access_token", "")
        if at.startswith("gAAAAA"):
            try:
                data["access_token"] = decrypt_secret(at)
            except Exception as dec_exc:
                logger.error(
                    "_cache_read: decrypt access_token failed for %s — "
                    "falling through to Postgres: %s",
                    service, dec_exc,
                )
                return {}

        rt = data.get("refresh_token", "")
        if rt.startswith("gAAAAA"):
            try:
                data["refresh_token"] = decrypt_secret(rt)
            except Exception as dec_exc:
                logger.warning(
                    "_cache_read: decrypt refresh_token failed for %s — "
                    "clearing RT, will reload from Postgres: %s",
                    service, dec_exc,
                )
                data["refresh_token"] = ""

        return data

    except Exception as exc:
        logger.error("_cache_read parse failed for %s: %s", service, exc)
        return {}


def _get_stored(service: str) -> dict:
    """
    Return the stored token for *service*.

    Order of preference:
      1. Redis cache (fast path)
      2. Postgres (authoritative fallback) — re-warms Redis on success
    """
    cached = _cache_read(service)
    if cached and cached.get("access_token"):
        return cached

    meta = _pg_load(service)
    if not meta:
        return {}

    version = int(meta.get("token_version", 0))
    _cache_warm(service, meta, version)

    return meta

def _store_token(
    service: str,
    access_token: str,
    expires_in: int,
    refresh_token: Optional[str] = None,
    refresh_token_expires_in: Optional[int] = None,
) -> None:
    """
    Persist a freshly-obtained token to Postgres (source of truth) and then
    warm the Redis cache.  This is the ONLY function that writes tokens.
    """
    expires_at = time.time() + expires_in - TOKEN_BUFFER_SECONDS
    rt_expires_at = time.time() + (refresh_token_expires_in or 5_184_000)

    meta = {
        "access_token":             access_token,
        "expires_at":               expires_at,
        "refresh_token":            refresh_token or "",
        "refresh_token_expires_at": rt_expires_at,
    }

    version = _pg_store(service, access_token, expires_at, refresh_token or "", rt_expires_at)

    meta["token_version"] = version
    _cache_warm(service, meta, version)

    _redis.delete(_fatal_counter_key(service))
    parts = service.split(":", 1)
    if len(parts) == 2:
        provider, client_id = parts
        from datetime import datetime, timezone
        payload = {
            "connected": True,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "scopes": "",
        }
        _redis.set(f"integration:status:{client_id}:{provider}", json.dumps(payload))


def _record_fatal_auth_error(service: str) -> int:
    """
    Increment the consecutive fatal-auth-error counter.
    Returns the new count.  Counter expires after DEAD_TOKEN_WINDOW seconds
    so transient outages don't accumulate.
    """
    key = _fatal_counter_key(service)
    pipe = _redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, DEAD_TOKEN_WINDOW)
    results = pipe.execute()
    count = int(results[0])
    logger.warning("Fatal auth error #%d for %s", count, service)
    return count


def _reset_fatal_counter(service: str) -> None:
    _redis.delete(_fatal_counter_key(service))


def _handle_dead_token(service: str, client_id: Optional[str]) -> None:
    """
    Mark an integration as disconnected and alert the client.
    Deduped so we only fire once per DEAD_TOKEN_ALERT_TTL window.
    """
    if not client_id:
        return

    alert_key = _dead_alert_key(f"{service}:{client_id}")
    if not _redis.set(alert_key, "1", nx=True, ex=DEAD_TOKEN_ALERT_TTL):
        logger.debug("_handle_dead_token dedup — skipping %s:%s", service, client_id)
        return

    from config.db_pool import get_conn
    from core.alerting import send_client_telegram_alert

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE client_integrations "
                "SET connected=FALSE, updated_at=NOW() "
                "WHERE client_id=%s AND provider=%s",
                (client_id, service),
            )
            cur.close()

        pipe = _redis.pipeline()
        pipe.delete(_token_key(f"{service}:{client_id}"))
        pipe.delete(_fatal_counter_key(f"{service}:{client_id}"))
        pipe.delete(f"cb:failures:{service}:{client_id}")
        pipe.delete(f"cb:open:{service}:{client_id}")
        pipe.execute()

        send_client_telegram_alert(
            client_id,
            f"Your {service.title()} connection has expired or been revoked. "
            f"Please reconnect: {settings.frontend_url}/client-dashboard/integration",
        )
        logger.warning("Dead token confirmed — marked disconnected: %s:%s", service, client_id)

    except Exception as exc:
        logger.error("_handle_dead_token failed %s:%s: %s", service, client_id, exc)

def _get_valid_token(service: str, client_id: Optional[str] = None) -> str:
    """
    Return a valid access token for *service*.
    """
    resolved = f"{service}:{client_id}" if client_id else service

    stored = _get_stored(resolved)
    if stored and time.time() < stored.get("expires_at", 0):
        return stored["access_token"]

    cb_key = f"cb:open:{service}:{client_id}"
    if _redis.exists(cb_key):
        if stored and stored.get("access_token"):
            logger.warning("CB open for %s — returning stale token", resolved)
            return stored["access_token"]
        raise RuntimeError(
            f"Circuit breaker open for {resolved} — "
            "integration temporarily unavailable"
        )

    lock_acquired = _redis.set(
        _lock_key(resolved), "1", nx=True, ex=REFRESH_LOCK_TTL
    )

    if not lock_acquired:
        for _ in range(int(REFRESH_LOCK_WAIT / REFRESH_LOCK_POLL)):
            time.sleep(REFRESH_LOCK_POLL)
            fresh = _get_stored(resolved)
            if fresh and time.time() < fresh.get("expires_at", 0):
                return fresh["access_token"]
        if stored and stored.get("access_token"):
            logger.warning("Lock timeout for %s — returning stale token", resolved)
            return stored["access_token"]
        raise RuntimeError(f"Token refresh timeout for {resolved}")

    try:
        refresh_token = stored.get("refresh_token", "") if stored else ""
        if not refresh_token:
            _handle_dead_token(service, client_id)
            raise RuntimeError(
                f"No refresh token for {resolved} — reconnect required"
            )

        return _refresh(service, refresh_token, client_id=client_id)

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (400, 401):
            count = _record_fatal_auth_error(resolved)
            if count >= DEAD_TOKEN_THRESHOLD:
                _handle_dead_token(service, client_id)
                raise RuntimeError(
                    f"Refresh token permanently expired for {resolved} — "
                    "reconnect required"
                )
            raise RuntimeError(
                f"Auth error #{count}/{DEAD_TOKEN_THRESHOLD} for {resolved} — "
                "will retry"
            )
        raise

    except Exception:
        raise

    finally:
        _redis.delete(_lock_key(resolved))


def _refresh(
    service: str,
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    """Dispatch to the correct provider refresh handler."""
    if not refresh_token:
        if client_id:
            _handle_dead_token(service, client_id)
        raise RuntimeError(f"No refresh token for {service}:{client_id}")

    handlers = {
        "xero":        _refresh_xero,
        "quickbooks":  _refresh_quickbooks,
        "google":      _refresh_google,
        "outlook":     _refresh_outlook,
        "paypal":      _refresh_paypal,
    }
    handler = handlers.get(service)
    if not handler:
        raise RuntimeError(f"Unknown OAuth service: {service}")

    return handler(refresh_token, client_id=client_id)


def _refresh_xero(
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    creds = base64.b64encode(
        f"{settings.xero_client_id}:{settings.xero_client_secret}".encode()
    ).decode()
    response = _post_with_retry(
        "https://identity.xero.com/connect/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        service="xero",
        client_id=client_id,
    )
    data = response.json()
    key = f"xero:{client_id}" if client_id else "xero"
    _store_token(
        key,
        data["access_token"],
        data["expires_in"],
        data.get("refresh_token") or refresh_token,
        data.get("refresh_token_expires_in", 5_184_000),
    )
    return data["access_token"]


def _refresh_quickbooks(
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    creds = base64.b64encode(
        f"{settings.quickbooks_client_id}:{settings.quickbooks_client_secret}".encode()
    ).decode()
    response = _post_with_retry(
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        service="quickbooks",
        client_id=client_id,
    )
    data = response.json()
    key = f"quickbooks:{client_id}" if client_id else "quickbooks"
    _store_token(
        key,
        data["access_token"],
        data["expires_in"],
        data.get("refresh_token") or refresh_token,
        data.get("refresh_token_expires_in", 7_776_000),
    )
    return data["access_token"]


def _refresh_google(
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    response = _post_with_retry(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     settings.google_client_id,
            "client_secret": settings.google_client_secret,
        },
        service="google",
        client_id=client_id,
        dead_on_invalid_grant=True,
    )
    data = response.json()
    key = f"google:{client_id}" if client_id else "google"
    _store_token(
        key,
        data["access_token"],
        data["expires_in"],
        refresh_token,
        15_552_000,
    )
    return data["access_token"]


def _refresh_outlook(
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    response = _post_with_retry(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "scope": (
                "offline_access Mail.Send Calendars.ReadWrite "
                "Files.ReadWrite.All Sites.ReadWrite.All"
            ),
        },
        service="outlook",
        client_id=client_id,
    )
    data = response.json()
    key = f"outlook:{client_id}" if client_id else "outlook"
    _store_token(
        key,
        data["access_token"],
        data["expires_in"],
        data.get("refresh_token") or refresh_token,
        data.get("refresh_token_expires_in", 15_552_000),
    )
    return data["access_token"]


def _refresh_paypal(
    refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    creds = base64.b64encode(
        f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
    ).decode()
    response = _post_with_retry(
        "https://api-m.paypal.com/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        service="paypal",
        client_id=client_id,
    )
    data = response.json()
    key = f"paypal:{client_id}" if client_id else "paypal"
    _store_token(
        key,
        data["access_token"],
        data["expires_in"],
        refresh_token,
        7_776_000,
    )
    return data["access_token"]

_NON_RETRYABLE_STATUS = {400, 401, 403}

_FATAL_GRANT_ERRORS = {
    "invalid_grant",
    "invalid_client",
    "unauthorized_client",
    "token_expired",
    "revoked_token",
}


def _post_with_retry(
    url: str,
    data: Optional[dict] = None,
    headers: Optional[dict] = None,
    service: str = "",
    client_id: Optional[str] = None,
    dead_on_invalid_grant: bool = False,
    max_attempts: int = 3,
) -> httpx.Response:
    """
    POST with exponential back-off.

    Auth errors (400/401) are NOT retried
    Network errors and 5xx responses are retried up to *max_attempts* times.
    """
    resolved = f"{service}:{client_id}" if client_id else service
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(max_attempts):
        try:
            response = httpx.post(
                url,
                headers=headers or {},
                data=data,
                timeout=15,
            )

            if response.status_code in _NON_RETRYABLE_STATUS:
                try:
                    err_body = response.json()
                except Exception:
                    err_body = {}

                error_code = err_body.get("error", "")
                is_fatal = (
                    error_code in _FATAL_GRANT_ERRORS
                    or (dead_on_invalid_grant and error_code == "invalid_grant")
                )

                if is_fatal:
                    logger.error(
                        "Fatal grant error '%s' for %s — "
                        "incrementing dead-token counter",
                        error_code, resolved,
                    )
                    count = _record_fatal_auth_error(resolved)
                    if count >= DEAD_TOKEN_THRESHOLD:
                        _handle_dead_token(service, client_id)
                else:
                    logger.warning(
                        "Non-fatal auth error %s for %s — "
                        "not incrementing dead-token counter: %s",
                        response.status_code, resolved, err_body,
                    )

                response.raise_for_status()

            response.raise_for_status()
            _reset_fatal_counter(resolved)
            return response

        except httpx.HTTPStatusError:
            raise

        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                wait = 2 ** attempt
                logger.warning(
                    "%s refresh attempt %d/%d failed (retrying in %ds): %s",
                    resolved, attempt + 1, max_attempts, wait, exc,
                )
                time.sleep(wait)

    raise RuntimeError(
        f"{service} token refresh failed after {max_attempts} attempts: {last_exc}"
    )

def bootstrap_token(
    service: str,
    access_token: str,
    expires_in: int,
    refresh_token: str,
    refresh_token_expires_in: Optional[int] = None,
) -> None:
    """
    Store a brand-new token obtained from an OAuth callback.
    Called by the integration callback routes.
    """
    _store_token(service, access_token, expires_in, refresh_token, refresh_token_expires_in)


def is_connected(service: str, client_id: Optional[str] = None) -> bool:
    """
    Return True if the service has a usable token (valid or refreshable).
    Does NOT attempt a refresh — purely a read.
    """
    resolved = f"{service}:{client_id}" if client_id else service
    stored = _get_stored(resolved)
    if not stored:
        return False
    if time.time() < stored.get("expires_at", 0):
        return True
    return bool(stored.get("refresh_token"))


def get_stored_token(service: str) -> dict:
    """Return the raw stored token dict (for inspection / refresh tasks)."""
    return _get_stored(service)


def do_refresh(
    service: str,
    stored_refresh_token: str,
    client_id: Optional[str] = None,
) -> str:
    """Explicitly refresh a token.  Called by the scheduled refresh task."""
    return _refresh(service, stored_refresh_token, client_id=client_id)


def handle_dead_token(service: str, client_id: Optional[str]) -> None:
    """Public wrapper — called from tasks.py when a refresh definitively fails."""
    _handle_dead_token(service, client_id)


def get_valid_token(service: str, client_id: Optional[str] = None) -> str:
    """
    Public entry point used by integration clients to obtain a valid token.
    Handles refresh, locking, and circuit-breaker checks transparently.
    """
    return _get_valid_token(service, client_id)