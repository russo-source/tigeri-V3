"""End-to-end tests for the force-change-on-first-sign-in flow.

These run through the real FastAPI app + SQLite test session, exercising the
sign-in → middleware-gate → change-password → cleared-flag chain. The
middleware short-circuits to 403 with ``code: "password_change_required"``
on every authed call other than the four allowed paths."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tigeri.api.app import create_app
from tigeri.api.deps import get_session
from tigeri.auth.models import User
from tigeri.auth.passwords import hash_password
from tigeri.tenant.models import Tenant


@pytest.fixture
async def client_with_must_change(session):
    """Seed an admin tenant + a user with must_change_password=true and
    return an httpx client wired to the real app + this DB session."""

    session.add(
        Tenant(id="tnt_t", slug="t", name="T", region="us", plan="pro", status="active")
    )
    session.add(
        User(
            id="usr_t",
            tenant_id="tnt_t",
            email="t@example.com",
            name="T User",
            role="admin",
            status="active",
            password_hash=hash_password("OldPass123!"),
            must_change_password=True,
        )
    )
    await session.commit()

    app = create_app()

    async def _session_override():
        yield session

    app.dependency_overrides[get_session] = _session_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sign_in_surfaces_flag(client_with_must_change):
    r = await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["must_change_password"] is True


@pytest.mark.asyncio
async def test_other_authed_calls_are_blocked(client_with_must_change):
    # Sign in to get the cookie
    r = await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200

    # Any other authed call returns 403 with the structured code so the
    # frontend can route to /change-password.
    r2 = await client_with_must_change.get("/admin/tenants")
    assert r2.status_code == 403
    body = r2.json()
    assert body.get("code") == "password_change_required"


@pytest.mark.asyncio
async def test_signin_works_even_with_stale_must_change_cookie(client_with_must_change):
    """A user who signed in once and then bounced back to /sign-in (without
    completing /change-password) must be able to sign in again. The middleware
    used to 403 the second sign-in because it saw a cookie + must_change=true
    and didn't recognise /auth/sign-in as an allowed path."""

    # First sign-in plants the cookie.
    r1 = await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r1.status_code == 200

    # Second sign-in (cookie present) must succeed, NOT 403 password_change_required.
    r2 = await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_change_password_clears_flag(client_with_must_change):
    # Sign in → get cookie
    await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )

    # Wrong current password is rejected
    bad = await client_with_must_change.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "NewPass456!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert bad.status_code == 401

    # Same-as-current is rejected
    same = await client_with_must_change.post(
        "/auth/change-password",
        json={"current_password": "OldPass123!", "new_password": "OldPass123!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert same.status_code == 400

    # Real change clears the flag
    ok = await client_with_must_change.post(
        "/auth/change-password",
        json={"current_password": "OldPass123!", "new_password": "NewPass456!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert ok.status_code == 204

    # Subsequent authed calls succeed (no longer blocked)
    me = await client_with_must_change.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["must_change_password"] is False

    # And the new password actually works for a fresh sign-in
    await client_with_must_change.post(
        "/auth/sign-out",
        headers={"Origin": "http://localhost:3000"},
    )
    re_sign_in = await client_with_must_change.post(
        "/auth/sign-in",
        json={"tenant_slug": "t", "email": "t@example.com", "password": "NewPass456!"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert re_sign_in.status_code == 200
    assert re_sign_in.json()["must_change_password"] is False
