import os
from collections.abc import AsyncIterator

# Force test database BEFORE tigeri modules import settings
os.environ.setdefault("TIGERI_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TIGERI_A2A_HMAC_SECRET", "test-secret")
os.environ.setdefault("TIGERI_A2A_REPLAY_WINDOW_SECONDS", "30")
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import tigeri.core.db as db_module
from tigeri.agents.admin.schemas import WorkflowInstance  # noqa: F401
from tigeri.agents.booking.schemas import Booking  # noqa: F401
from tigeri.agents.client_onboarding.schemas import Onboarding  # noqa: F401
from tigeri.agents.contract_management.schemas import Contract  # noqa: F401
from tigeri.agents.expense.schemas import CardTransaction, Expense  # noqa: F401
from tigeri.agents.financial_reporting.schemas import FinancialReport  # noqa: F401
from tigeri.agents.invoice.schemas import Invoice  # noqa: F401
from tigeri.agents.staffing.schemas import Roster, StaffMember  # noqa: F401
from tigeri.actions.models import PendingAction  # noqa: F401
from tigeri.audit.record import AuditRecord  # noqa: F401
from tigeri.audit_chain.models import AuditLog  # noqa: F401
from tigeri.auth.models import Session as UserSession, User  # noqa: F401
from tigeri.chat.models import ChatFeedback, ChatMessage, ChatThread  # noqa: F401
from tigeri.integrations.models import TenantIntegration  # noqa: F401
from tigeri.integrations.tenant_creds import TenantIntegrationCredentials  # noqa: F401
from tigeri.tenant.models import AgentDeployment, Integration, Tenant  # noqa: F401
from tigeri.core.db import Base
from tigeri.core.config import get_settings


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(get_settings().database_url, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db_module._engine = eng
    db_module._sessionmaker = async_sessionmaker(eng, expire_on_commit=False)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()
    db_module._engine = None
    db_module._sessionmaker = None


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s


@pytest_asyncio.fixture
async def tenant_scoped_session(engine, tenant_id: str = "t_test"):
    """Yield an AsyncSession with `app.current_tenant_id = :tid` SET LOCAL.

    PR-1 (entry 17) fixture: every DB-touching test should use this in
    preference to the bare `session` fixture, so tests fail loudly if
    the test's code path drops tenant context. On sqlite the SET LOCAL
    is a no-op (application-layer WHERE still enforces); on Postgres
    this is the RLS bootstrap.
    """
    from tigeri.core.db import session_scope

    async with session_scope(tenant_id=tenant_id) as s:
        yield s


@pytest_asyncio.fixture
async def bypass_rls_session(engine, reason: str = "auth"):
    """Yield an AsyncSession with an acknowledged BYPASSRLS reason.

    Used by tests that exercise pre-scope or cross-tenant code paths
    (auth resolution, sweepers, inbound channel webhook actor lookup,
    langgraph checkpointer). PR-2 wires the actual SET ROLE call to
    one of the named Postgres BYPASSRLS roles.
    """
    from tigeri.core.db import session_scope

    async with session_scope(bypass_rls=reason) as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_replay_cache():
    from tigeri.a2a.signing import _replay_cache

    _replay_cache._seen.clear()
    yield
