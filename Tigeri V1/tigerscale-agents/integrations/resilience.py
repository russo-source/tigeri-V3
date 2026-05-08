from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable, Optional, TypeVar

import redis

from config.settings import settings

logger = logging.getLogger(__name__)
_redis = redis.from_url(settings.redis_url, decode_responses=True)

F = TypeVar("F", bound=Callable[..., Any])

# Retry decorator defaults.
RETRY_ATTEMPTS: int = 4
RETRY_BASE_DELAY: float = 2.0

# Circuit-breaker thresholds.
# Raised from 3/60 to 5/120 to prevent false-positive opens on transient spikes.
BREAKER_FAILURE_THRESHOLD: int = 5
BREAKER_WINDOW_SECONDS: int = 120
BREAKER_OPEN_SECONDS: int = 300
PROBE_LOCK_TTL: int = 30

# HTTP status codes that are client-side errors — never retry, never trip breaker.
_NON_RETRYABLE_STATUS: frozenset[int] = frozenset({400, 401, 403, 404, 405, 409, 422})

# HTTP status codes that ARE transient infrastructure failures.
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is OPEN."""


class ProbeInProgressError(CircuitOpenError):
    """
    Raised when the circuit is HALF-OPEN and another worker already holds
    the probe lock.  Callers should surface this as "recovering — retry shortly"
    rather than a hard error.
    """


class XeroValidationError(Exception):
    """
    Raised when Xero returns a 400 ValidationException.

    This is a DATA error, not an infrastructure error.  It is:
      - Non-retryable
      - Does NOT trip the circuit breaker
      - Does NOT increment the dead-token counter
      - Carries human-readable ``messages`` for the user
    """
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


class QuickBooksValidationError(Exception):
    """
    Equivalent of XeroValidationError for QuickBooks Fault responses.
    Non-retryable, does NOT trip the breaker.
    """
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))

def _extract_xero_validation_errors(body: str) -> list[str]:
    """Parse Xero 400 ValidationException body → list of human-readable strings."""
    try:
        data = json.loads(body)
        errors: list[str] = []
        for element in data.get("Elements", []):
            for err in element.get("ValidationErrors", []):
                msg = err.get("Message", "")
                if msg:
                    errors.append(msg)
        return errors if errors else [data.get("Message", "Xero validation error")]
    except Exception:
        return ["Xero validation error"]


def _extract_quickbooks_errors(body: str) -> list[str]:
    """Parse QuickBooks Fault body → list of human-readable strings."""
    try:
        data = json.loads(body)
        errors: list[str] = []
        fault = data.get("Fault", {})
        for err in fault.get("Error", []):
            detail = err.get("Detail") or err.get("Message") or str(err)
            errors.append(detail)
        return errors if errors else ["QuickBooks validation error"]
    except Exception:
        return ["QuickBooks validation error"]

def _is_non_retryable(exc: Exception) -> bool:
    """
    Return True for errors that must NOT be retried and must NOT trip the
    circuit breaker.  These are always data / client errors.
    """
    import httpx

    if isinstance(exc, (XeroValidationError, QuickBooksValidationError, ValueError)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code

        if status == 400:
            try:
                body = exc.response.text
                data = json.loads(body)
                if data.get("Type") == "ValidationException" or data.get("Elements"):
                    raise XeroValidationError(
                        _extract_xero_validation_errors(body)
                    )
                # QuickBooks Fault
                if "Fault" in data:
                    raise QuickBooksValidationError(
                        _extract_quickbooks_errors(body)
                    )
            except (XeroValidationError, QuickBooksValidationError):
                raise
            except Exception:
                pass

        return status in _NON_RETRYABLE_STATUS

    return False


def _is_transient(exc: Exception) -> bool:
    """Return True for errors that ARE worth retrying."""
    import httpx

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout,
                        httpx.ConnectError, httpx.RemoteProtocolError)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS

    return True

def with_retry(func: F) -> F:
    """
    Async retry decorator with exponential back-off.

    - CircuitOpenError: re-raised immediately (no retry).
    - Non-retryable errors: re-raised immediately (no retry).
    - Everything else: retried up to RETRY_ATTEMPTS times.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[Exception] = None

        for attempt in range(RETRY_ATTEMPTS):
            try:
                return func(*args, **kwargs)

            except CircuitOpenError:
                logger.warning(
                    "%s aborted — circuit open (attempt %d)",
                    func.__name__, attempt + 1,
                )
                raise

            except Exception as exc:
                try:
                    if _is_non_retryable(exc):
                        logger.warning(
                            "%s non-retryable error (attempt %d): %s",
                            func.__name__, attempt + 1, exc,
                        )
                        raise
                except (XeroValidationError, QuickBooksValidationError):
                    raise
                except Exception:
                    raise

                last_exc = exc
                logger.warning(
                    "%s attempt %d/%d failed: %s",
                    func.__name__, attempt + 1, RETRY_ATTEMPTS, exc,
                )

        logger.error(
            "%s failed after %d attempts: %s",
            func.__name__, RETRY_ATTEMPTS, last_exc,
        )
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]

def with_sync_retry(max_attempts: int = 3, base_delay: float = 1.0):
    """
    Sync retry decorator with exponential back-off.
    Suitable for use inside Celery task bodies.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import time
            last_exc: Optional[Exception] = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)

                except CircuitOpenError:
                    raise

                except Exception as exc:
                    try:
                        if _is_non_retryable(exc):
                            raise
                    except (XeroValidationError, QuickBooksValidationError):
                        raise
                    except Exception:
                        raise

                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = base_delay ** attempt
                        logger.warning(
                            "%s attempt %d/%d failed: %s. Retrying in %.1fs",
                            func.__name__, attempt + 1, max_attempts, exc, delay,
                        )
                        time.sleep(delay)

            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]
    return decorator


class CircuitBreaker:
    """
    Redis-backed circuit breaker per service.

    States
    ------
    closed    — normal operation
    open      — all calls rejected for BREAKER_OPEN_SECONDS
    half-open — one probe allowed; others get ProbeInProgressError
    """

    FAILURE_THRESHOLD: int = BREAKER_FAILURE_THRESHOLD
    WINDOW_SECONDS: int = BREAKER_WINDOW_SECONDS
    OPEN_SECONDS: int = BREAKER_OPEN_SECONDS

    def __init__(self, service: str) -> None:
        self.service     = service
        self.failure_key = f"cb:failures:{service}"
        self.open_key    = f"cb:open:{service}"
        self.probe_key   = f"cb:probe_lock:{service}"

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        state = self._state()

        if state == "open":
            logger.warning("CB OPEN — rejecting call for '%s'", self.service)
            raise CircuitOpenError(
                "The integration is temporarily unavailable. "
                "Please try again in a few minutes."
            )

        if state == "half-open":
            return self._probe_call(func, *args, **kwargs)

        # Closed — normal call.
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except CircuitOpenError:
            raise

        except Exception as exc:
            try:
                if _is_non_retryable(exc):
                    raise
            except (XeroValidationError, QuickBooksValidationError):
                raise
            except Exception:
                raise

            self._on_failure()
            raise

    def __call__(self, func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)
        return wrapper  # type: ignore[return-value]

    def reset(self) -> None:
        """Manually reset the breaker (e.g. after a successful OAuth refresh)."""
        _redis.delete(self.failure_key, self.open_key, self.probe_key)
        logger.info("Circuit breaker manually reset: '%s'", self.service)

    def status(self) -> dict:
        state    = self._state()
        failures = int(_redis.get(self.failure_key) or 0) # type: ignore
        ttl      = int(_redis.ttl(self.open_key) or 0) if state in ("open", "half-open") else 0 # type: ignore
        return {
            "service":    self.service,
            "state":      state,
            "failures":   failures,
            "reopen_in":  max(int(ttl), 0),
            "threshold": self.FAILURE_THRESHOLD,
            "window_s":  self.WINDOW_SECONDS,
        }

    def _state(self) -> str:
        if not _redis.exists(self.open_key):
            return "closed"
        ttl = int(_redis.ttl(self.open_key) or 0) # type: ignore
        if ttl <= 0:
            return "half-open"
        return "open"

    def _on_success(self) -> None:
        _redis.delete(self.failure_key, self.open_key, self.probe_key)

    def _on_failure(self) -> None:
        pipe = _redis.pipeline()
        pipe.incr(self.failure_key)
        pipe.expire(self.failure_key, BREAKER_WINDOW_SECONDS)
        results = pipe.execute()
        failure_count = int(results[0])

        if failure_count >= BREAKER_FAILURE_THRESHOLD:
            already_open = _redis.exists(self.open_key)
            _redis.setex(self.open_key, BREAKER_OPEN_SECONDS, "1")

            if not already_open:
                logger.critical(
                    "Circuit breaker OPENED for '%s' after %d failures in %ds",
                    self.service, failure_count, BREAKER_WINDOW_SECONDS,
                )
                self._send_ops_alert(
                    f"[OPS ALERT] Circuit breaker OPEN\n"
                    f"Service:  {self.service}\n"
                    f"Failures: {failure_count} in {BREAKER_WINDOW_SECONDS}s\n"
                    f"Auto-recovery in {BREAKER_OPEN_SECONDS // 60} min"
                )
        else:
            logger.warning(
                "CB failure %d/%d for '%s'",
                failure_count, self.FAILURE_THRESHOLD, self.service,
            )

    def _probe_call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        acquired = _redis.set(self.probe_key, "1", nx=True, ex=PROBE_LOCK_TTL)
        if not acquired:
            raise ProbeInProgressError(
                "Integration is recovering — please try again in a moment."
            )
        try:
            result = func(*args, **kwargs)
            self._on_success()
            logger.info("CB probe SUCCESS — closing breaker for '%s'", self.service)
            return result

        except CircuitOpenError:
            raise

        except Exception as exc:
            _redis.setex(self.open_key, BREAKER_OPEN_SECONDS, "1")
            logger.warning(
                "CB probe FAILED — reopening for '%s': %s", self.service, exc
            )
            raise

        finally:
            _redis.delete(self.probe_key)

    @staticmethod
    def _send_ops_alert(message: str) -> None:
        try:
            from core.alerting import send_ops_telegram_alert
            send_ops_telegram_alert(message)
        except Exception as exc:
            logger.debug("Ops alert failed (non-fatal): %s", exc)