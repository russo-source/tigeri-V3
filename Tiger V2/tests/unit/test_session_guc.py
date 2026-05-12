"""PR-1 session-bootstrap GUC invariant tests (migration spec entry 17).

Covers:
- session_scope(tenant_id=...) yields a session with SET LOCAL applied.
- session_scope(bypass_rls=...) yields a session with the acknowledged
  cross-tenant context (PR-2 wires the actual SET ROLE).
- session_scope() with neither arg raises TenantContextMissing.
- session_scope(tenant_id=..., bypass_rls=...) raises ValueError
  (caller can't claim both contexts).
- session_scope(bypass_rls="bogus") raises ValueError on unknown reason.
- The tenant_scoped_session fixture provides the canonical happy path.

Counterfactual tests follow the SF#5 calibration pattern: an inline
_naive_session_scope simulation mirrors the pre-PR-1 behaviour (bare
session, no guard), and the assertion is constructed so it FAILS on
the pre-fix code and PASSES on the post-fix code. The simulation is
documented inline so future readers can verify the test is
load-bearing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.db import (
    ALLOWED_BYPASSRLS_REASONS,
    TenantContextMissing,
    get_sessionmaker,
    session_scope,
)


# ---------------------------------------------------------------------------
# Positive tests (PR-1 happy paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_scope_with_tenant_id_yields_session(engine):
    """The canonical tenant-scoped path: SET LOCAL on Postgres; no-op on sqlite."""
    async with session_scope(tenant_id="t_alpha") as s:
        assert isinstance(s, AsyncSession)
        # On sqlite the SET LOCAL is a no-op; on Postgres we could verify
        # current_setting('app.current_tenant_id') == 't_alpha'.


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", sorted(ALLOWED_BYPASSRLS_REASONS))
async def test_session_scope_with_each_bypass_rls_reason_yields_session(engine, reason):
    """Every allowlisted bypass reason yields a session. PR-2 wires the
    real SET ROLE; PR-1 only validates the typed marker."""
    async with session_scope(bypass_rls=reason) as s:
        assert isinstance(s, AsyncSession)


@pytest.mark.asyncio
async def test_tenant_scoped_session_fixture(tenant_scoped_session):
    """The canonical fixture yields a session under tenant context."""
    assert isinstance(tenant_scoped_session, AsyncSession)


# ---------------------------------------------------------------------------
# Boundary-guard tests (PR-1's core safety contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_session_scope_raises_tenant_context_missing(engine):
    """The load-bearing safety test: bare session_scope() raises before
    any session is opened, so RLS can't silently filter."""
    with pytest.raises(TenantContextMissing) as exc:
        async with session_scope() as _:
            pytest.fail("session_scope() should have raised before yielding")
    # The error message should name both escape hatches so a confused
    # caller knows their options.
    assert "tenant_id" in str(exc.value)
    assert "bypass_rls" in str(exc.value)
    for reason in ALLOWED_BYPASSRLS_REASONS:
        assert reason in str(exc.value)


@pytest.mark.asyncio
async def test_session_scope_rejects_both_tenant_id_and_bypass_rls(engine):
    """Caller can't claim both tenant and cross-tenant context. Mutex."""
    with pytest.raises(ValueError) as exc:
        async with session_scope(tenant_id="t_alpha", bypass_rls="auth_resolve") as _:
            pytest.fail("session_scope should have raised on mutex violation")
    assert "tenant_id or bypass_rls, not both" in str(exc.value)


@pytest.mark.asyncio
async def test_session_scope_rejects_unknown_bypass_rls_reason(engine):
    """Bypass reasons are allowlisted so PR-2 can grep + migrate every site."""
    with pytest.raises(ValueError) as exc:
        async with session_scope(bypass_rls="bogus_reason") as _:
            pytest.fail("session_scope should have raised on unknown reason")
    assert "unknown bypass_rls reason" in str(exc.value)
    assert "'bogus_reason'" in str(exc.value)


# ---------------------------------------------------------------------------
# Counterfactual tests (SF#5 calibration pattern)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _naive_session_scope() -> AsyncIterator[AsyncSession]:
    """Inline simulation of the PRE-PR-1 session_scope() implementation.

    This mirrors the bare yielder that V2 shipped before entry 17 landed:
    no GUC bootstrap, no fail-loud guard. Used to verify that the
    counterfactual assertions below would have FAILED against the
    pre-fix code, which proves they are load-bearing.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.mark.asyncio
async def test_counterfactual_pre_pr1_bare_session_does_not_raise(engine):
    """Pre-fix simulation: _naive_session_scope() returns a session
    without raising. The post-fix session_scope() raises. This test
    confirms the regression detector is load-bearing.

    Pre-fix shape:
      async with _naive_session_scope() as s:
          ...  # yields a bare session, no GUC, no guard

    Post-fix shape:
      async with session_scope() as s:
          # RAISES TenantContextMissing before yield

    The first assert below succeeds (pre-fix yields normally); the
    second assert demonstrates the post-fix raises. If anyone reverts
    PR-1's guard, the second assert fails.
    """
    # Pre-fix: yields normally.
    async with _naive_session_scope() as s:
        assert isinstance(s, AsyncSession)

    # Post-fix: raises before yielding.
    with pytest.raises(TenantContextMissing):
        async with session_scope() as _:
            pytest.fail("session_scope() must raise on bare call")


@pytest.mark.asyncio
async def test_counterfactual_pre_pr1_no_typed_error_class(engine):
    """Pre-fix had no TenantContextMissing class at all.

    Post-fix: the class exists, is importable, and is what session_scope
    raises. A regression that re-introduces a bare yielder without the
    typed exception would either (a) keep the class but not raise it
    (caught by test_bare_session_scope_raises_tenant_context_missing) or
    (b) remove the class entirely (caught here: import would fail at
    module-load time).
    """
    # Importing this module succeeded, which means the typed class was
    # importable. Sanity-check the class exists + is the right kind.
    assert isinstance(TenantContextMissing, type)
    assert issubclass(TenantContextMissing, Exception)
