from abc import ABC
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agent_card.registry import get_registry
from tigeri.agent_card.schema import AgentCard, TrustTier
from tigeri.audit.sink_local import AuditEvent, emit
from tigeri.core.ids import trace_id as new_trace_id


@dataclass
class AgentRunContext:
    tenant_id: str
    actor: str
    trace_id: str

    @classmethod
    def new(cls, tenant_id: str, actor: str) -> "AgentRunContext":
        return cls(tenant_id=tenant_id, actor=actor, trace_id=new_trace_id())


class BaseAgent(ABC):
    agent_id: str

    def __init__(self) -> None:
        self.card: AgentCard = get_registry().get(self.agent_id)

    @property
    def trust_tier(self) -> TrustTier:
        return self.card.default_trust_tier

    async def audit(
        self,
        session: AsyncSession,
        ctx: AgentRunContext,
        action: str,
        target_resource: str,
        outcome: str,
        payload: dict | None = None,
    ) -> None:
        await emit(
            session,
            AuditEvent(
                actor=f"{self.agent_id}:{ctx.actor}",
                action=action,
                target_resource=target_resource,
                tenant_id=ctx.tenant_id,
                outcome=outcome,
                trace_id=ctx.trace_id,
                payload=payload,
            ),
        )
