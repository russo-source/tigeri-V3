"""DB engine + session factory + tenant-context bootstrap.

Phase 6.5 RLS migration — PR-1 (entry 17): every session-yielder must
either set the `app.current_tenant_id` GUC (tenant role path) or
acknowledge a known cross-tenant bypass reason (auth, sweeper, inbound
channel, langgraph). Bare sessions raise `TenantContextMissing` at
yield time so the RLS USING clause cannot silently filter all rows
post-migration.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from tigeri.core.config import get_settings


class Base(DeclarativeBase):
    pass


class TenantContextMissing(Exception):
    """Raised when a session is yielded without tenant context.

    Under Postgres RLS (Phase 6.5+), every query needs either:
    - `app.current_tenant_id` set via SET LOCAL (tenant role path), OR
    - An allowlisted BYPASSRLS role active via SET ROLE.

    Bare sessions silently return zero rows under RLS (USING clause
    evaluates `tenant_id = NULL`, which is unknown). This exception
    converts that silent failure into a noisy one at the boundary.

    See migration spec entry 17 in CLAUDE.md.
    """


# BYPASSRLS reasons are acknowledged in PR-1 but not yet wired to real
# Postgres roles — PR-2 (entries 7, 8, 14, 15) provisions
# `tigeri_auth_role`, `tigeri_sweeper_role`, `tigeri_inbound_channel_role`,
# `tigeri_langgraph_role` and switches session.execute("SET ROLE ...")
# inside the matching branches below.
ALLOWED_BYPASSRLS_REASONS = frozenset({
    "auth",            # pre-scope identity resolution (auth/scope.py, auth/sessions.py)
    "sweeper",         # cleanup_expired cron jobs across tenants
    "inbound_channel", # telegram webhook actor resolution + capability-token consume
    "langgraph",       # PostgresSaver raw conn pool (cross-tenant by thread_id contract)
})


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, future=True, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope(
    *,
    tenant_id: str | None = None,
    bypass_rls: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession with tenant context established.

    Exactly one of `tenant_id` or `bypass_rls` MUST be provided. A bare
    call (both None) raises `TenantContextMissing` so callers can't
    accidentally bypass the boundary.

    - `tenant_id="..."`: execute `SET LOCAL app.current_tenant_id = :tid`
      on session start (Postgres only; no-op on other dialects).
    - `bypass_rls="<reason>"`: acknowledged cross-tenant context. PR-2
      will wire SET ROLE to the matching BYPASSRLS role. For now this is
      a typed marker — the session still runs under the default role,
      which means RLS (when applied in PR-3) will still filter. The
      typed marker lets PR-2 grep + migrate every bypass site
      systematically.
    """
    if tenant_id is None and bypass_rls is None:
        raise TenantContextMissing(
            "session_scope() requires either tenant_id=... or bypass_rls=... "
            f"(allowed bypass reasons: {sorted(ALLOWED_BYPASSRLS_REASONS)})"
        )
    if tenant_id is not None and bypass_rls is not None:
        raise ValueError("session_scope: provide tenant_id or bypass_rls, not both")
    if bypass_rls is not None and bypass_rls not in ALLOWED_BYPASSRLS_REASONS:
        raise ValueError(
            f"session_scope: unknown bypass_rls reason {bypass_rls!r}. "
            f"Allowed: {sorted(ALLOWED_BYPASSRLS_REASONS)}"
        )

    sm = get_sessionmaker()
    async with sm() as session:
        if tenant_id is not None:
            bind = session.get_bind()
            if bind.dialect.name == "postgresql":
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            # On non-Postgres (sqlite tests) the SET LOCAL is a no-op;
            # tenant isolation is still enforced at the application
            # layer via explicit WHERE clauses (the audit register
            # confirmed this for all 101 query sites).
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
