"""Lock in the CSRF allow-list invariants.

The CsrfOriginMiddleware blocks state-changing requests whose Origin (or, on
absence, Referer) isn't in our allow-list. Webhook + OAuth-callback routes
bypass that check via ``CSRF_EXEMPT_PREFIXES`` because they're called by
external systems whose Origin we can't predict — they rely on a different
auth mechanism (state-nonce, secret token).

These tests guard the contract: every prefix in the exemption list must
correspond to a real route, and conversely, the routes that need exemption
(callbacks, webhooks) must be covered. A regression where someone adds a new
webhook endpoint but forgets to add its prefix would silently 403 in
production — these tests catch that at PR time."""

from __future__ import annotations

from tigeri.api.app import create_app
from tigeri.api.middleware import CSRF_EXEMPT_PREFIXES


def _route_paths(app) -> set[str]:
    return {
        getattr(r, "path", "") for r in app.routes if getattr(r, "path", "")
    }


def test_every_csrf_exempt_prefix_matches_a_real_route():
    """An exemption pointing at a route that no longer exists is dead config
    — it doesn't break anything but it suggests we don't know what's
    actually exempt anymore. Fail loudly."""

    app = create_app()
    paths = _route_paths(app)

    for prefix in CSRF_EXEMPT_PREFIXES:
        assert any(p.startswith(prefix) for p in paths), (
            f"CSRF exempt prefix {prefix!r} matches no live route. "
            "Either remove from CSRF_EXEMPT_PREFIXES or restore the route."
        )


def test_oauth_callbacks_are_csrf_exempt():
    """Every /v1/integrations/callback/<provider> route MUST be CSRF-exempt
    — providers can't send our Origin header. Catch the case where someone
    adds a new provider's callback but forgets to extend the exempt list."""

    app = create_app()
    paths = _route_paths(app)
    callback_paths = [p for p in paths if "/integrations/callback/" in p]

    assert callback_paths, "expected at least one OAuth callback route"
    for path in callback_paths:
        # Strip the leading /api prefix if present (production nginx adds it,
        # tests don't).
        normalised = path[len("/api"):] if path.startswith("/api/") else path
        assert any(normalised.startswith(p) for p in CSRF_EXEMPT_PREFIXES), (
            f"OAuth callback {path!r} is not CSRF-exempt. Add its prefix to "
            "CSRF_EXEMPT_PREFIXES in tigeri.api.middleware."
        )


def test_telegram_webhook_is_csrf_exempt():
    """Telegram POSTs to our webhook with no Origin we can validate — auth
    is via the secret-token header inside the route handler. Make sure the
    CSRF gate doesn't preempt that."""

    app = create_app()
    paths = _route_paths(app)
    tg_webhook = [p for p in paths if "telegram/webhook" in p]
    assert tg_webhook, "telegram/webhook route missing"

    for path in tg_webhook:
        normalised = path[len("/api"):] if path.startswith("/api/") else path
        assert any(normalised.startswith(p) for p in CSRF_EXEMPT_PREFIXES), (
            f"telegram webhook {path!r} must be in CSRF_EXEMPT_PREFIXES"
        )
