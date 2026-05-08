from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext, BaseAgent
from tigeri.agents.expense.categoriser import categorise
from tigeri.agents.expense.policy import ExpensePolicy
from tigeri.agents.expense.schemas import (
    CardTransaction,
    Expense,
    ExpenseInput,
    ExpenseOutput,
)
from tigeri.agents.invoice.adapters.inbox import InboxAdapter, LocalInboxAdapter
from tigeri.agents.invoice.adapters.ocr import OCRAdapter, default_ocr_adapter
from tigeri.core.concurrency import advisory_xact_lock, expense_match_lock_key
from tigeri.core.ids import new_id


class ExpenseAgent(BaseAgent):
    agent_id = "expense_agent"

    def __init__(
        self,
        inbox: InboxAdapter | None = None,
        ocr: OCRAdapter | None = None,
        policy: ExpensePolicy | None = None,
    ) -> None:
        super().__init__()
        self.inbox = inbox or LocalInboxAdapter()
        self.ocr = ocr or default_ocr_adapter()
        self.policy = policy or ExpensePolicy()

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: ExpenseInput,
    ) -> ExpenseOutput:
        expense_id = new_id("exp")

        # Capability 1: scan
        body, media_type = await self.inbox.fetch_bytes(request.image_ref)
        image_hash = sha256(body).hexdigest()
        await self.audit(session, ctx, "scan", expense_id, "OK", {"hash": image_hash})

        # Capability 2: extract
        raw = await self.ocr.extract_fields(body, media_type)
        merchant = str(raw.get("vendor_name", "UNKNOWN"))
        amount = Decimal(str(raw.get("amount_total", "0")))
        currency = str(raw.get("currency", "USD")).upper()
        await self.audit(
            session,
            ctx,
            "extract",
            expense_id,
            "OK",
            {"merchant": merchant, "amount": str(amount), "currency": currency},
        )

        # Capability 3: categorise
        category = categorise(merchant)
        await self.audit(session, ctx, "categorise", expense_id, "OK", {"category": category})

        # Capability 4: policy_check
        policy_status, reason = self.policy.evaluate(category, amount)
        await self.audit(
            session, ctx, "policy_check", expense_id, policy_status, {"reason": reason}
        )

        # Capability 5: reconcile
        recon_status, matched_id = await self._reconcile(
            session, ctx.tenant_id, expense_id, merchant, amount, request.captured_at
        )
        await self.audit(
            session,
            ctx,
            "reconcile",
            expense_id,
            recon_status,
            {"matched_card_txn_id": matched_id},
        )

        # Capability 6: submit
        row = Expense(
            id=expense_id,
            tenant_id=ctx.tenant_id,
            submitter_id=request.submitter_id,
            merchant=merchant,
            amount=amount,
            currency=currency,
            category=category,
            policy_status=policy_status,
            reconciliation_status=recon_status,
            matched_card_txn_id=matched_id,
            image_hash=image_hash,
            captured_at=request.captured_at.astimezone(UTC)
            if request.captured_at.tzinfo
            else request.captured_at.replace(tzinfo=UTC),
        )
        session.add(row)
        await self.audit(session, ctx, "submit", expense_id, "SUBMITTED", None)

        return ExpenseOutput(
            tenant_id=ctx.tenant_id,
            expense_id=expense_id,
            merchant=merchant,
            amount=amount,
            currency=currency,
            category=category,
            policy_status=policy_status,  # type: ignore[arg-type]
            reconciliation_status=recon_status,  # type: ignore[arg-type]
            matched_card_txn_id=matched_id,
        )

    async def _reconcile(
        self,
        session: AsyncSession,
        tenant_id: str,
        expense_id: str,
        merchant: str,
        amount: Decimal,
        when: datetime,
    ) -> tuple[str, str]:
        """Find an unmatched card transaction for this expense and bind them.

        Audit-driven changes (2026-04-28):
          1. Per-(tenant, merchant) advisory lock around the candidate scan
             so two concurrent expenses can't both pick the same card txn.
          2. ``SELECT ... FOR UPDATE SKIP LOCKED`` on the candidates so a
             second waiter only ever sees rows the first didn't pick.
          3. Persist ``matched_expense_id = expense_id`` directly. The old
             code wrote a placeholder ``"PENDING"`` and relied on a never-
             implemented commit-time fixup, which left card txns stuck.
        """
        when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
        window = timedelta(days=2)

        await advisory_xact_lock(
            session, expense_match_lock_key(tenant_id, merchant)
        )

        stmt = (
            select(CardTransaction)
            .where(
                CardTransaction.tenant_id == tenant_id,
                CardTransaction.merchant == merchant,
                CardTransaction.amount == amount,
                CardTransaction.matched_expense_id.is_(None),
                CardTransaction.occurred_at >= when - window,
                CardTransaction.occurred_at <= when + window,
            )
            .with_for_update(skip_locked=True)
        )
        candidates = (await session.scalars(stmt)).all()
        if not candidates:
            return "UNMATCHED", ""
        match = candidates[0]
        match.matched_expense_id = expense_id
        return "MATCHED", match.id
