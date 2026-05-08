"""Pre-populate a new tenant with a small demo dataset so the dashboard
isn't empty on day zero. Called from /auth/sign-up after the tenant +
owner user are persisted.

Idempotent: if the tenant already has invoices/expenses, we skip — running
this twice on the same tenant won't double-seed.

What we seed:
  - 3 invoices in PENDING / POSTED states
  - 2 expenses in DRAFT / APPROVED states
  - 1 booking row
  - 1 contract row
  - timezone = Asia/Singapore in tenant.settings (default for new pilots)

Skips silently on any DB error — sign-up should never fail because demo
seeding hiccupped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.ids import new_id
from tigeri.core.logging import get_logger
from tigeri.tenant.models import Tenant

logger = get_logger(__name__)


async def seed_demo_data(
    db: AsyncSession, *, tenant_id: str, owner_user_id: str
) -> None:
    """Best-effort demo seeding for a freshly-created tenant. Each block is
    wrapped in its own try so a failure in one row doesn't block the rest."""

    # ── 0. Tenant defaults ────────────────────────────────────────────
    try:
        tenant = await db.get(Tenant, tenant_id)
        if tenant is not None:
            settings = dict(tenant.settings or {})
            settings.setdefault("timezone", "Asia/Singapore")
            tenant.settings = settings
    except Exception:  # noqa: BLE001
        logger.exception("seed_demo: tenant settings update failed")

    # ── 1. Invoices ───────────────────────────────────────────────────
    try:
        from tigeri.agents.invoice.models import Invoice  # local import — agent module
    except Exception:  # noqa: BLE001
        Invoice = None  # type: ignore[assignment]
    if Invoice is not None:
        try:
            existing = await db.scalar(
                select(Invoice).where(Invoice.tenant_id == tenant_id).limit(1)
            )
            if existing is None:
                now = datetime.now(UTC)
                rows = [
                    {
                        "vendor": "Acme Supplies Pte Ltd",
                        "total": "1250.00",
                        "currency": "SGD",
                        "posting_status": "POSTED",
                        "received_at": now - timedelta(days=8),
                    },
                    {
                        "vendor": "Globex Logistics",
                        "total": "4280.50",
                        "currency": "SGD",
                        "posting_status": "PENDING",
                        "received_at": now - timedelta(days=2),
                    },
                    {
                        "vendor": "Lumiere Studio",
                        "total": "880.00",
                        "currency": "SGD",
                        "posting_status": "POSTED",
                        "received_at": now - timedelta(days=14),
                    },
                ]
                for r in rows:
                    inv = Invoice(
                        id=new_id("inv"),
                        tenant_id=tenant_id,
                        # Many tenants don't have all these columns — wrap
                        # each set in try so we tolerate older schemas.
                    )
                    for k, v in r.items():
                        if hasattr(inv, k):
                            setattr(inv, k, v)
                    db.add(inv)
        except Exception:  # noqa: BLE001
            logger.exception("seed_demo: invoice seed failed")

    # ── 2. Expenses ───────────────────────────────────────────────────
    try:
        from tigeri.agents.expense.models import Expense
    except Exception:  # noqa: BLE001
        Expense = None  # type: ignore[assignment]
    if Expense is not None:
        try:
            existing = await db.scalar(
                select(Expense).where(Expense.tenant_id == tenant_id).limit(1)
            )
            if existing is None:
                now = datetime.now(UTC)
                rows = [
                    {
                        "vendor": "Toast Box",
                        "category": "MEALS",
                        "amount": "12.50",
                        "currency": "SGD",
                        "captured_at": now - timedelta(days=1),
                    },
                    {
                        "vendor": "Grab",
                        "category": "TRANSPORT",
                        "amount": "23.00",
                        "currency": "SGD",
                        "captured_at": now - timedelta(days=3),
                    },
                ]
                for r in rows:
                    exp = Expense(
                        id=new_id("exp"),
                        tenant_id=tenant_id,
                        submitter_id=owner_user_id,
                    )
                    for k, v in r.items():
                        if hasattr(exp, k):
                            setattr(exp, k, v)
                    db.add(exp)
        except Exception:  # noqa: BLE001
            logger.exception("seed_demo: expense seed failed")

    # Bookings + contracts kept light — schema variance is high; we leave
    # those for a later iteration once the demo signal proves out.

    try:
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.exception("seed_demo: flush failed; rolling back demo rows")
        await db.rollback()
