"""HTTP middleware: request-id correlation + CSRF Origin/Referer guard.

These are kept in one module so app.py wires them with two add_middleware
calls instead of N. Both are pure-Python and have no external deps.

Why an Origin check rather than a CSRF token? We already issue
``SameSite=None; Secure`` cookies because the prod frontend is cross-origin
to the API (sslip.io frontend → sslip.io/api/* via nginx → uvicorn). Without
SameSite=Strict, modern browsers still send cookies on cross-site POSTs from
attacker-controlled pages. The Origin header is set by the browser on every
cross-origin request and cannot be spoofed by JavaScript on a malicious
page; rejecting POST/PUT/PATCH/DELETE with an Origin not in the allow-list
closes the standard CSRF attack vector.

Limitations to call out:
  - Webhook endpoints (Telegram, OAuth callbacks) bypass the check via
    ``CSRF_EXEMPT_PREFIXES`` since they're called by external systems whose
    Origin we can't predict. They have their own auth (secret token, OAuth
    state nonce).
  - Same-origin POSTs from the API host itself have no Origin set on
    redirects; we accept missing-Origin with a Referer fallback.
  - HEAD/GET/OPTIONS are never blocked (no state change).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from urllib.parse import urlparse

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from tigeri.core.config import get_settings

logger = logging.getLogger(__name__)


# Routes that may legitimately receive cross-origin POSTs from external
# parties and authenticate by other means (HMAC, OAuth state nonce).
CSRF_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/v1/integrations/callback/",   # OAuth provider redirects (state-nonce auth)
    "/v1/integrations/telegram/webhook",  # Telegram bot push (secret-token auth)
)

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _allowed_origins() -> set[str]:
    """Mirrors the CORS allowlist in app.py. Both must agree for a clean
    posture; whenever you add a domain to one, add it to both.
    """
    return {
        "http://localhost:3000",
        "https://100-48-88-95.sslip.io",
        "http://ec2-100-48-88-95.compute-1.amazonaws.com",
    }


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a stable id, surface it on the response,
    and bind it onto the request scope so downstream handlers can include
    it in structured logs.
    """

    HEADER = "x-request-id"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get(self.HEADER) or uuid.uuid4().hex
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            # Re-raise after logging; let FastAPI's default 500 handler emit.
            logger.exception("unhandled request error", extra={"request_id": rid})
            raise
        response.headers[self.HEADER] = rid
        return response


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests whose Origin (or, on absence, Referer)
    isn't in the allow-list. Skips webhook + OAuth-callback routes.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in STATE_CHANGING_METHODS:
            return await call_next(request)

        path = request.url.path
        # FastAPI's underlying ASGI path includes the API prefix (/api/...)
        # in deployed envs; nginx strips it. Match against both shapes.
        normalized = path[len("/api"):] if path.startswith("/api/") else path
        if any(normalized.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        allowed = _allowed_origins()
        ok = False
        if origin:
            ok = origin in allowed
        elif referer:
            try:
                p = urlparse(referer)
                ok = f"{p.scheme}://{p.netloc}" in allowed
            except Exception:  # noqa: BLE001
                ok = False
        else:
            # No Origin and no Referer — typical for non-browser clients
            # (curl, server-to-server). Allow only if there's no auth cookie
            # (a CSRF attack against an unauthenticated endpoint isn't
            # really a CSRF). For dev-mode (local), be permissive.
            settings = get_settings()
            has_cookie = "tigeri_session" in request.cookies
            ok = (not has_cookie) or settings.env == "local"

        if not ok:
            logger.warning(
                "csrf_origin_rejected",
                extra={
                    "request_id": getattr(request.state, "request_id", "-"),
                    "method": request.method,
                    "path": normalized,
                    "origin": origin or "(none)",
                    "referer": referer or "(none)",
                },
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "origin not allowed"},
            )

        return await call_next(request)


# Routes a session with `must_change_password=true` is allowed to call. Every
# other authed request returns 403 with a `password_change_required` code so
# the frontend can route to /change-password.
#
# /auth/sign-in and /auth/sign-up are explicitly listed because a user with a
# stale must-change cookie may legitimately sign in again (e.g. they bounced
# off the change-password page and want to start over). Those endpoints
# create a fresh session anyway — there's no security benefit to gating them.
PASSWORD_CHANGE_ALLOWED_PATHS: tuple[str, ...] = (
    "/auth/sign-in",
    "/auth/sign-up",
    "/auth/sign-out",
    "/auth/change-password",
    "/auth/me",
    "/healthz",
    "/readyz",
)


class MustChangePasswordMiddleware(BaseHTTPMiddleware):
    """Block API calls from sessions whose user has must_change_password=true.

    Why middleware and not a per-route Depends? Putting it on every authed
    route is a maintenance footgun — one missed route is a silent bypass.
    Doing the check once here covers every route that uses the session
    cookie, including future ones.

    This is a hot-path query (DB on every request). Mitigations:
    - Skip when there's no session cookie at all (anonymous traffic).
    - Skip the always-allowed paths above.
    - SELECT only the boolean flag — index on sessions.token_hash is already
      there and `users.must_change_password` is small."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        normalized = path[len("/api"):] if path.startswith("/api/") else path
        if any(normalized.startswith(p) for p in PASSWORD_CHANGE_ALLOWED_PATHS):
            return await call_next(request)

        cookie = request.cookies.get("tigeri_session")
        if not cookie:
            return await call_next(request)

        # Lazy import to avoid circular dependency: middleware module would
        # otherwise import the auth models at startup before SQLAlchemy
        # finishes registering.
        from tigeri.auth.models import Session as UserSession, User
        from tigeri.core.db import get_sessionmaker

        token_hash = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        sm = get_sessionmaker()
        async with sm() as db:
            row = await db.execute(
                select(User.must_change_password)
                .join(UserSession, UserSession.user_id == User.id)
                .where(UserSession.token_hash == token_hash)
            )
            flag = row.scalar_one_or_none()

        if flag:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "password_change_required",
                    "code": "password_change_required",
                },
            )

        return await call_next(request)
