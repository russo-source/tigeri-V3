"""Contract Management Agent — Priority 7, Phase 1, RECOMMENDER tier."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from langgraph.graph import StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext
from tigeri.agents.contract_management.extractor import (
    ContractExtractor,
    default_contract_extractor,
)
from tigeri.agents.contract_management.schemas import (
    Contract,
    ContractInput,
    ContractOutput,
    KeyTerm,
    LifecycleState,
)
from tigeri.agents.invoice.adapters.inbox import InboxAdapter, LocalInboxAdapter
from tigeri.core.ids import new_id
from tigeri.graph.base import BaseGraphAgent, current_db_session
from tigeri.graph.state import BaseAgentState

RENEWAL_WARNING_WINDOW = timedelta(days=60)


class ContractGraphState(BaseAgentState, total=False):
    request: ContractInput
    contract_id: str
    body: bytes
    media_type: str
    document_hash: str
    extracted: dict[str, Any]
    lifecycle: LifecycleState
    output: ContractOutput


class ContractManagementAgent(BaseGraphAgent):
    agent_id = "contract_management_agent"
    state_schema = ContractGraphState

    def __init__(
        self,
        inbox: InboxAdapter | None = None,
        extractor: ContractExtractor | None = None,
        checkpointer=None,
    ) -> None:
        self.inbox = inbox or LocalInboxAdapter()
        self.extractor = extractor or default_contract_extractor()
        super().__init__(checkpointer=checkpointer)

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: ContractInput,
        *,
        session_id: str = "default",
        user_id: str = "anonymous",
    ) -> ContractOutput:
        contract_id = new_id("ctr")
        final = await self.run_graph(
            ctx=ctx,
            session_id=session_id,
            user_id=user_id,
            db_session=session,
            initial={"request": request, "contract_id": contract_id},
        )
        return final["output"]

    def build_graph(self) -> StateGraph:
        g: StateGraph = StateGraph(ContractGraphState)
        g.add_node("ingest", self._node_ingest)
        g.add_node("extract_terms", self._node_extract_terms)
        g.add_node("track", self._node_track)
        g.add_node("schedule_alerts", self._node_schedule_alerts)
        g.add_node("surface_obligations", self._node_surface_obligations)
        g.add_node("render_register", self._node_render_register)
        g.set_entry_point("ingest")
        g.add_edge("ingest", "extract_terms")
        g.add_edge("extract_terms", "track")
        g.add_edge("track", "schedule_alerts")
        g.add_edge("schedule_alerts", "surface_obligations")
        g.add_edge("surface_obligations", "render_register")
        g.add_edge("render_register", self.end())
        return g

    async def _node_ingest(self, state: ContractGraphState) -> dict:
        request = state["request"]
        body, media_type = await self.inbox.fetch_bytes(request.document_ref)
        digest = sha256(body).hexdigest()
        await self._audit(
            state,
            "ingest",
            state["contract_id"],
            "OK",
            {"media_type": media_type, "hash": digest},
        )
        return {"body": body, "media_type": media_type, "document_hash": digest}

    async def _node_extract_terms(self, state: ContractGraphState) -> dict:
        extracted = await self.extractor.extract_terms(state["body"], state["media_type"])
        await self._audit(
            state,
            "extract_terms",
            state["contract_id"],
            "OK",
            {
                "counterparty": extracted["counterparty"],
                "expiry_date": extracted["expiry_date"],
                "key_term_count": len(extracted["key_terms"]),
            },
        )
        return {"extracted": extracted}

    async def _node_track(self, state: ContractGraphState) -> dict:
        extracted = state["extracted"]
        expiry = self._iso_to_dt(extracted["expiry_date"])
        now = datetime.now(UTC)
        if expiry < now:
            lifecycle: LifecycleState = "EXPIRED"
        elif expiry < now + RENEWAL_WARNING_WINDOW:
            lifecycle = "EXPIRING"
        else:
            lifecycle = "ACTIVE"
        await self._audit(
            state, "track", state["contract_id"], lifecycle, {"expiry_utc": expiry.isoformat()}
        )
        return {"lifecycle": lifecycle}

    async def _node_schedule_alerts(self, state: ContractGraphState) -> dict:
        # Slice 1: log when alerts would fire. Real calendar integration lands later.
        expiry = self._iso_to_dt(state["extracted"]["expiry_date"])
        warn_at = (expiry - RENEWAL_WARNING_WINDOW).isoformat()
        await self._audit(
            state,
            "schedule_alerts",
            state["contract_id"],
            "OK",
            {"warning_at": warn_at, "expires_at": expiry.isoformat()},
        )
        return {}

    async def _node_surface_obligations(self, state: ContractGraphState) -> dict:
        terms = state["extracted"]["key_terms"]
        deadline_terms = [t for t in terms if "date" in t["term"] or "deadline" in t["term"]]
        await self._audit(
            state,
            "surface_obligations",
            state["contract_id"],
            "OK",
            {"flagged": len(deadline_terms)},
        )
        return {}

    async def _node_render_register(self, state: ContractGraphState) -> dict:
        request = state["request"]
        extracted = state["extracted"]
        contract_id = state["contract_id"]
        db = current_db_session()
        effective = self._iso_to_dt(extracted["effective_date"])
        expiry = self._iso_to_dt(extracted["expiry_date"])

        existing = await db.scalar(
            select(Contract).where(
                Contract.tenant_id == state["session"]["tenant_id"],
                Contract.document_hash == state["document_hash"],
            )
        )
        if existing is not None:
            lifecycle: LifecycleState = state.get("lifecycle") or "ACTIVE"  # type: ignore[assignment]
            existing.lifecycle_state = lifecycle
            row = existing
        else:
            row = Contract(
                id=contract_id,
                tenant_id=state["session"]["tenant_id"],
                counterparty=extracted["counterparty"],
                effective_date=effective,
                expiry_date=expiry,
                auto_renewal=extracted["auto_renewal"],
                contract_value=extracted.get("contract_value") or Decimal("0"),
                currency=extracted["currency"],
                key_terms_json={"items": extracted["key_terms"]},
                lifecycle_state=state.get("lifecycle") or "ACTIVE",
                document_hash=state["document_hash"],
                uploader_id=request.uploader_id,
                ingested_at=datetime.now(UTC),
            )
            db.add(row)

        await self._audit(
            state, "render_register", row.id, "OK", {"lifecycle": row.lifecycle_state}
        )
        output = ContractOutput(
            tenant_id=state["session"]["tenant_id"],
            contract_id=row.id,
            counterparty=row.counterparty,
            effective_date=effective,
            expiry_date=expiry,
            auto_renewal=row.auto_renewal,
            key_terms=[KeyTerm(**t) for t in extracted["key_terms"]],
            lifecycle_state=row.lifecycle_state,  # type: ignore[arg-type]
        )
        return {"output": output}

    @staticmethod
    def _iso_to_dt(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = datetime.now(UTC) + timedelta(days=365)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    async def _audit(
        self,
        state: ContractGraphState,
        action: str,
        target: str,
        outcome: str,
        payload: dict[str, Any] | None,
    ) -> None:
        ctx = AgentRunContext(
            tenant_id=state["session"]["tenant_id"],
            actor=f"user:{state['session']['user_id']}",
            trace_id=state["trace_id"],
        )
        await self.audit(current_db_session(), ctx, action, target, outcome, payload)
