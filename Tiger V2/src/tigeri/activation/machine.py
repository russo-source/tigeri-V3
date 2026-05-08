from dataclasses import dataclass, field
from typing import Any

from tigeri.activation.discovery import (
    CapabilityInventory,
    CRMHandle,
    CRMUnreachable,
    DiscoveryError,
    IntrospectionTimeout,
    discover,
)
from tigeri.activation.reasoning import (
    ClientObjective,
    ReasoningResult,
    VerticalContext,
    rank_agents,
)
from tigeri.activation.states import ActivationState
from tigeri.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ActivationContext:
    tenant_id: str
    state: ActivationState = ActivationState.S0_SIGNED_IN
    inventory: CapabilityInventory | None = None
    vertical: VerticalContext | None = None
    objectives: list[ClientObjective] = field(default_factory=list)
    recommendations: ReasoningResult | None = None
    deployed_agents: list[str] = field(default_factory=list)
    last_error: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, new_state: ActivationState, reason: str = "") -> None:
        self.history.append({"from": self.state.value, "to": new_state.value, "reason": reason})
        logger.info("activation_transition", tenant_id=self.tenant_id, **self.history[-1])
        self.state = new_state


async def start(ctx: ActivationContext, handle: CRMHandle) -> ActivationContext:
    """S0 → S1 → S2 → S3."""

    if ctx.state != ActivationState.S0_SIGNED_IN:
        raise ValueError(f"start() requires S0, got {ctx.state}")
    ctx.transition(ActivationState.S1_CRM_DISCOVERY, "user start")

    if handle.mcp_endpoint:
        ctx.transition(ActivationState.S2_MCP_CONNECT, "MCP available")
    else:
        ctx.transition(ActivationState.S2_API_CONNECT, "MCP absent, using API")

    try:
        ctx.inventory = await discover(handle, ctx.tenant_id)
    except IntrospectionTimeout as e:
        ctx.last_error = str(e)
        ctx.transition(ActivationState.S_FAIL_INTROSPECTION, ctx.last_error)
        return ctx
    except CRMUnreachable as e:
        ctx.last_error = str(e)
        ctx.transition(ActivationState.S_FAIL_NO_CRM, ctx.last_error)
        return ctx
    except DiscoveryError as e:
        ctx.last_error = str(e)
        ctx.transition(ActivationState.S_FAIL_INTEGRATION, ctx.last_error)
        return ctx

    ctx.transition(ActivationState.S3_CAPABILITY_INVENTORY, "inventory committed")
    ctx.transition(ActivationState.S4_OBJECTIVE_INTAKE, "ready for objectives")
    return ctx


def submit_objectives(
    ctx: ActivationContext, vertical: VerticalContext, objectives: list[ClientObjective]
) -> ActivationContext:
    if ctx.state != ActivationState.S4_OBJECTIVE_INTAKE:
        raise ValueError(f"submit_objectives requires S4, got {ctx.state}")
    if ctx.inventory is None:
        raise ValueError("capability inventory missing")

    ctx.vertical = vertical
    ctx.objectives = objectives
    ctx.transition(ActivationState.S5_AGENT_REASONING, "objectives confirmed")

    result = rank_agents(ctx.tenant_id, vertical, ctx.inventory, objectives)
    ctx.recommendations = result

    if not result.ranked_recommendations:
        ctx.transition(ActivationState.S_FAIL_NO_MATCH, "no agent matched")
        return ctx

    ctx.transition(ActivationState.S6_RECOMMENDATION_REVIEW, "recommendations ready")
    return ctx


def deploy(ctx: ActivationContext, agent_ids: list[str]) -> ActivationContext:
    if ctx.state != ActivationState.S6_RECOMMENDATION_REVIEW:
        raise ValueError(f"deploy requires S6, got {ctx.state}")
    if not agent_ids:
        ctx.transition(ActivationState.S_FAIL_REJECT, "user accepted no agents")
        return ctx

    ctx.transition(ActivationState.S7_AGENT_DEPLOY, f"deploying {len(agent_ids)} agents")
    ctx.deployed_agents = agent_ids
    ctx.transition(ActivationState.S8_ACTIVE, "deployment health-checked")
    return ctx
