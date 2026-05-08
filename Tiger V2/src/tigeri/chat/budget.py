"""Per-tenant daily token budget for LLM calls.

The orchestrator calls ``check_budget`` before issuing a Claude request and
``record_usage`` after each turn finishes. When the running total for the
current UTC day crosses ``settings.chat_tenant_daily_token_budget``, the
``check_budget`` call returns ``(False, ...)`` and the chat loop bails with a
friendly "daily budget reached" message instead of issuing the request.

We use the existing ``audit_records`` table as the persistence surface for
cumulative-token bookkeeping rather than introducing a new table — the same
HMAC chain already covers it, the (tenant_id, timestamp_utc) index already
makes the daily roll-up cheap, and operators get token usage in the same
audit feed they're already watching.

The counter is best-effort: a race between two concurrent requests can let
both pass the budget check by a small margin. Acceptable for a soft cap;
turn this into a SELECT ... FOR UPDATE if hard accounting is needed."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.audit.record import AuditRecord
from tigeri.core.ids import new_id

_BUDGET_ACTION = "llm_token_usage"


async def used_today(session: AsyncSession, tenant_id: str) -> int:
    """Sum input+output tokens recorded for this tenant since 00:00 UTC.

    payload_json is text — we parse it. The hot path is bounded: at most a
    few hundred chat turns per tenant per day in the pilot. If this ever
    needs to scale, switch to a dedicated `token_ledger` table with a
    daily partial index."""

    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = await session.scalars(
        select(AuditRecord.payload_json)
        .where(AuditRecord.tenant_id == tenant_id)
        .where(AuditRecord.action == _BUDGET_ACTION)
        .where(AuditRecord.timestamp_utc >= start)
    )
    total = 0
    for raw in rows:
        if not raw:
            continue
        try:
            total += int(json.loads(raw).get("tokens", 0))
        except (ValueError, TypeError):
            continue
    return total


async def check_budget(
    session: AsyncSession, tenant_id: str, *, daily_cap: int
) -> tuple[bool, int, int]:
    """Return ``(ok, used, remaining)``. ``ok`` is False when the next call
    would exceed the cap. ``daily_cap`` of 0 disables the check."""

    if daily_cap <= 0:
        return (True, 0, 0)
    used = await used_today(session, tenant_id)
    return (used < daily_cap, used, max(daily_cap - used, 0))


async def record_usage(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    session_id: str,
) -> None:
    """Persist one LLM round-trip's token usage. Total of zero is allowed
    (the LLM occasionally reports 0 in error) — we just skip the write."""

    total = max(int(input_tokens or 0), 0) + max(int(output_tokens or 0), 0)
    if total <= 0:
        return

    payload = json.dumps(
        {
            "tokens": total,
            "input": int(input_tokens or 0),
            "output": int(output_tokens or 0),
            "model": model,
        }
    )

    rec = AuditRecord(
        id=new_id("aud"),
        actor=f"user:{user_id}",
        action=_BUDGET_ACTION,
        target_resource=f"chat_session:{session_id}",
        tenant_id=tenant_id,
        outcome="OK",
        trace_id=session_id,
        payload_json=payload,
    )
    session.add(rec)
    await session.flush()


def reset_window_seconds() -> int:
    """Seconds until the next UTC midnight — used in the user-facing message."""
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())
