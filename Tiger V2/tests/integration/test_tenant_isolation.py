"""Cross-tenant isolation suite.

Negative tests: a request authenticated as tenant A must NEVER be able to
read or write tenant B's data, even when the URL or body explicitly names
tenant B's resource id.

The test exercises the FastAPI app via httpx.AsyncClient with overridden
``get_scope`` / ``require_admin`` dependencies, so we don't need to set up
real cookies — we inject the scope directly. Every endpoint that takes a
tenant-scoped path or body field is covered."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from datetime import UTC, datetime

from tigeri.agents.invoice.schemas import Invoice
from tigeri.api.app import create_app
from tigeri.auth.admin import require_admin
from tigeri.auth.scope import TenantScope, get_scope
from tigeri.tenant.models import Tenant


def _scope(tenant_id: str = "tnt_a", user_id: str = "usr_a", role: str = "member") -> TenantScope:
    return TenantScope(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        session_id=None,
    )


@pytest.fixture
async def client(session):
    """ASGI app wired up with a fixed scope for tnt_a."""

    app = create_app()
    app.dependency_overrides[get_scope] = lambda: _scope("tnt_a", "usr_a", "admin")
    app.dependency_overrides[require_admin] = lambda: _scope("tnt_a", "usr_a", "admin")

    # Wire DB
    from tigeri.api.deps import get_session

    async def _session_override():
        yield session

    app.dependency_overrides[get_session] = _session_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def two_tenants_with_invoices(session):
    """Seed tenants A and B, plus one invoice in each."""
    for tid, slug, name in [("tnt_a", "a", "Tenant A"), ("tnt_b", "b", "Tenant B")]:
        session.add(Tenant(id=tid, slug=slug, name=name, region="us", plan="pro", status="active"))
    await session.flush()

    now = datetime.now(UTC)
    a_inv = Invoice(
        id="inv_a",
        tenant_id="tnt_a",
        vendor_name="V-A",
        currency="USD",
        amount_total=100,
        tax_total=0,
        invoice_number="A-001",
        validation_status="VALIDATED",
        approval_status="APPROVED",
        posting_status="POSTED",
        document_hash="hash-a",
        received_at=now,
    )
    b_inv = Invoice(
        id="inv_b",
        tenant_id="tnt_b",
        vendor_name="V-B",
        currency="USD",
        amount_total=200,
        tax_total=0,
        invoice_number="B-001",
        validation_status="VALIDATED",
        approval_status="APPROVED",
        posting_status="POSTED",
        document_hash="hash-b",
        received_at=now,
    )
    session.add_all([a_inv, b_inv])
    await session.commit()


@pytest.mark.asyncio
async def test_tenant_a_cannot_read_tenant_b_invoice(client, two_tenants_with_invoices):
    """GET /invoices/inv_b while authed as tnt_a must 404 — never 200 with B's data."""
    r = await client.get("/invoices/inv_b")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_tenant_a_can_read_own_invoice(client, two_tenants_with_invoices):
    r = await client.get("/invoices/inv_a")
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "tnt_a"


@pytest.mark.asyncio
async def test_body_tenant_id_must_match_scope(client):
    """When a route body includes tenant_id, it must equal the scope's
    tenant_id. Pinning tenant_id from the URL/body is a classic IDOR — we
    explicitly reject it on agent invokes."""

    payload = {
        "tenant_id": "tnt_b",  # mismatched on purpose
        "source": "API",
        "document": {"media_type": "text/plain", "content_ref": "inline:hello"},
        "received_at": datetime.now(UTC).isoformat(),
    }

    r = await client.post("/agents/invoice_agent/invoke", json=payload)
    assert r.status_code == 400, r.text
    assert "tenant_id" in r.text.lower()


@pytest.mark.asyncio
async def test_admin_route_blocks_when_role_is_member(session):
    """Even a real cookie scope returns 403 from /admin/* if role != admin/owner."""
    app = create_app()
    app.dependency_overrides[get_scope] = lambda: _scope(role="member")
    # require_admin uses get_scope underneath in the production code path,
    # so we *don't* override it — we want to verify the real guard fires.
    from tigeri.api.deps import get_session

    async def _session_override():
        yield session

    app.dependency_overrides[get_session] = _session_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/tenants")
        assert r.status_code == 403, r.text
    app.dependency_overrides.clear()
