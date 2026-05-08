"""Postgres advisory-lock helpers — substitutes for Redis where the work is
already inside a single SQL transaction.

Per the audit, several agents have read-then-insert flows where two
concurrent requests can both miss a conflict and both persist incompatible
rows (booking double-confirms, expense matching the same card txn twice).
Wrapping the conflict-check + insert in a per-resource transaction-scoped
advisory lock serialises only the at-risk resource, not the whole tenant.

On non-Postgres dialects (sqlite in tests) the lock is a no-op; the test
runner usually has a single writer anyway.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def advisory_xact_lock(session: AsyncSession, key: str) -> None:
    """Acquire a Postgres transaction-scoped advisory lock keyed on ``key``.

    The lock releases automatically at COMMIT or ROLLBACK. Two transactions
    with the same key serialise; different keys don't block each other.
    Hashing happens server-side via ``hashtextextended`` — Postgres turns
    the variable-length text into the bigint pg_advisory_lock requires.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))").bindparams(k=key)
    )


def booking_lock_key(tenant_id: str, venue_id: str) -> str:
    return f"booking:{tenant_id}:{venue_id}"


def expense_match_lock_key(tenant_id: str, merchant: str) -> str:
    return f"expense_match:{tenant_id}:{merchant}"
