"""Capability dispatcher used by /actions/confirm.

The orchestrator owns the canonical tool registry (see
``tigeri.agents.orchestrator.tools.REGISTRY``). When a write action is
proposed, the orchestrator stops short of executing it and emits a
``tool_proposed`` event. /actions/confirm later resolves the saved
capability through this dispatcher and runs it server-side with the original
parameters.

Resolution is lazy (deferred import) to avoid load-time circular deps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class UnknownCapabilityError(LookupError):
    """The proposed capability is not in the orchestrator REGISTRY anymore."""


async def dispatch_capability(
    *,
    capability: str,
    parameters: dict[str, Any],
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    session_id: str | None,
    public_base_url: str,
) -> dict[str, Any]:
    """Run the orchestrator tool named ``capability`` with ``parameters``.

    Raises UnknownCapabilityError if the tool is no longer registered.
    Lets the tool's own exceptions propagate; the caller (actions route) is
    responsible for marking the action failed and writing an audit entry.
    """
    # Lazy import — the orchestrator module pulls in every agent and would
    # cause an import cycle if loaded at the top of this file.
    from tigeri.agents.orchestrator.tools import REGISTRY

    fn = REGISTRY.get(capability)
    if fn is None:
        raise UnknownCapabilityError(capability)

    return await fn(
        parameters,
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id or "default",
        public_base_url=public_base_url,
    )


def is_write_capability(capability: str) -> bool:
    """Indicates whether a capability needs the propose -> confirm gate."""

    from tigeri.agents.orchestrator.tools import WRITE_TOOLS

    return capability in WRITE_TOOLS
