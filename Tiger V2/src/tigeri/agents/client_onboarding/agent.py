"""Client Onboarding Agent — Priority 8, Phase 1, ACTOR_GATED tier.

Slice 1 stubs the KYC/KYB provider (always PASS unless the registration_id
contains the word "block"), the project-plan template (in-process), and the
kickoff calendar booking (records intent but doesn't hit a real calendar).
The handoff capability emits an event that the Admin Agent (Priority 3) can
consume in a future slice — for now the audit row is the contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langgraph.graph import StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext
from tigeri.agents.client_onboarding.schemas import (
    COInput,
    COOutput,
    KYBStatus,
    KYCStatus,
    Onboarding,
)
from tigeri.core.ids import new_id
from tigeri.graph.base import BaseGraphAgent, current_db_session
from tigeri.graph.state import BaseAgentState


PROJECT_TEMPLATE: list[dict[str, str]] = [
    {"step": "kickoff", "due_offset_days": "0"},
    {"step": "discovery", "due_offset_days": "3"},
    {"step": "configuration", "due_offset_days": "7"},
    {"step": "go_live", "due_offset_days": "14"},
]


class COGraphState(BaseAgentState, total=False):
    request: COInput
    onboarding_id: str
    provisioning_ref: str
    kyc_status: KYCStatus
    kyb_status: KYBStatus
    project_plan_ref: str
    project_plan_steps: list[dict[str, str]]
    kickoff_meeting_id: str
    output: COOutput


class ClientOnboardingAgent(BaseGraphAgent):
    agent_id = "client_onboarding_agent"
    state_schema = COGraphState

    async def invoke(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        request: COInput,
        *,
        session_id: str = "default",
        user_id: str = "anonymous",
    ) -> COOutput:
        onboarding_id = new_id("onb")
        final = await self.run_graph(
            ctx=ctx,
            session_id=session_id,
            user_id=user_id,
            db_session=session,
            initial={"request": request, "onboarding_id": onboarding_id},
        )
        return final["output"]

    def build_graph(self) -> StateGraph:
        g: StateGraph = StateGraph(COGraphState)
        g.add_node("provision", self._node_provision)
        g.add_node("kyc", self._node_kyc)
        g.add_node("kyb", self._node_kyb)
        g.add_node("generate_plan", self._node_generate_plan)
        g.add_node("schedule_kickoff", self._node_schedule_kickoff)
        g.add_node("handoff", self._node_handoff)
        g.set_entry_point("provision")
        g.add_edge("provision", "kyc")
        g.add_edge("kyc", "kyb")
        g.add_edge("kyb", "generate_plan")
        g.add_edge("generate_plan", "schedule_kickoff")
        g.add_edge("schedule_kickoff", "handoff")
        g.add_edge("handoff", self.end())
        return g

    async def _node_provision(self, state: COGraphState) -> dict:
        ref = f"db://onboardings/{state['onboarding_id']}"
        await self._audit(
            state,
            "provision",
            state["onboarding_id"],
            "OK",
            {"client": state["request"].client_record.legal_name, "ref": ref},
        )
        return {"provisioning_ref": ref}

    async def _node_kyc(self, state: COGraphState) -> dict:
        status = self._stub_check(state["request"], "kyc")
        await self._audit(state, "kyc", state["onboarding_id"], status, None)
        return {"kyc_status": status}

    async def _node_kyb(self, state: COGraphState) -> dict:
        status = self._stub_check(state["request"], "kyb")
        await self._audit(state, "kyb", state["onboarding_id"], status, None)
        return {"kyb_status": status}

    async def _node_generate_plan(self, state: COGraphState) -> dict:
        plan_ref = f"db://project_plans/{state['onboarding_id']}"
        await self._audit(
            state,
            "generate_plan",
            state["onboarding_id"],
            "OK",
            {"plan_ref": plan_ref, "steps": len(PROJECT_TEMPLATE)},
        )
        return {"project_plan_ref": plan_ref, "project_plan_steps": list(PROJECT_TEMPLATE)}

    async def _node_schedule_kickoff(self, state: COGraphState) -> dict:
        meeting_id = new_id("mtg")
        when = datetime.now(UTC) + timedelta(days=3)
        await self._audit(
            state,
            "schedule_kickoff",
            state["onboarding_id"],
            "OK",
            {
                "meeting_id": meeting_id,
                "when_utc": when.isoformat(),
                "with": state["request"].client_record.primary_contact.email,
            },
        )
        return {"kickoff_meeting_id": meeting_id}

    async def _node_handoff(self, state: COGraphState) -> dict:
        request = state["request"]
        onboarding_id = state["onboarding_id"]
        completed_at = datetime.now(UTC)
        db = current_db_session()
        kyc_status = state.get("kyc_status") or "NEEDS_REVIEW"
        kyb_status = state.get("kyb_status") or "NEEDS_REVIEW"
        plan_ref = state.get("project_plan_ref") or ""
        meeting_id = state.get("kickoff_meeting_id") or ""

        row = Onboarding(
            id=onboarding_id,
            tenant_id=state["session"]["tenant_id"],
            client_legal_name=request.client_record.legal_name,
            registration_id=request.client_record.registration_id,
            primary_contact_name=request.client_record.primary_contact.name,
            primary_contact_email=request.client_record.primary_contact.email,
            signed_contract_ref=request.signed_contract_ref,
            kyc_status=kyc_status,
            kyb_status=kyb_status,
            project_plan_ref=plan_ref,
            kickoff_meeting_id=meeting_id,
            plan_json={"items": state.get("project_plan_steps") or []},
            completed_at=completed_at,
        )
        db.add(row)
        await self._audit(
            state,
            "handoff",
            onboarding_id,
            "OK",
            {"to": "admin_agent", "event": "client_onboarded"},
        )
        output = COOutput(
            tenant_id=state["session"]["tenant_id"],
            onboarding_id=onboarding_id,
            kyc_status=kyc_status,
            kyb_status=kyb_status,
            project_plan_ref=plan_ref,
            kickoff_meeting_id=meeting_id,
            completed_at=completed_at,
        )
        return {"output": output}

    @staticmethod
    def _stub_check(request: COInput, kind: Literal["kyc", "kyb"]) -> KYCStatus:
        # Slice 1: any registration_id containing 'block' fails;
        # 'review' triggers manual review; everything else passes.
        rid = request.client_record.registration_id.lower()
        if "block" in rid:
            return "FAIL"
        if "review" in rid:
            return "NEEDS_REVIEW"
        return "PASS"

    async def _audit(
        self,
        state: COGraphState,
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
