from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from tigeri.activation.discovery import CRMHandle
from tigeri.activation.machine import (
    ActivationContext,
    deploy,
    start,
    submit_objectives,
)
from tigeri.activation.reasoning import ClientObjective, VerticalContext
from tigeri.activation.states import ActivationState
from tigeri.auth.admin import require_admin
from tigeri.auth.scope import TenantScope

router = APIRouter(prefix="/activation", tags=["activation"])

# Slice 1: in-memory context per tenant. A future slice persists this.
_contexts: dict[str, ActivationContext] = {}


class StartRequest(BaseModel):
    source_system: str
    api_base_url: str | None = None
    mcp_endpoint: str | None = None


class ObjectiveRequest(BaseModel):
    industry: str
    employee_count: int
    venues_or_locations: int
    regulated: bool
    objectives: list[dict]


class DeployRequest(BaseModel):
    agent_ids: list[str]


def _ctx_for(tenant_id: str) -> ActivationContext:
    ctx = _contexts.get(tenant_id)
    if ctx is None:
        ctx = ActivationContext(tenant_id=tenant_id)
        _contexts[tenant_id] = ctx
    return ctx


@router.post("/start")
async def post_start(req: StartRequest, scope: TenantScope = Depends(require_admin)) -> dict:
    tenant_id = scope.tenant_id
    ctx = _ctx_for(tenant_id)
    if ctx.state != ActivationState.S0_SIGNED_IN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"context already in {ctx.state}")
    handle = CRMHandle(
        source_system=req.source_system,
        api_base_url=req.api_base_url,
        mcp_endpoint=req.mcp_endpoint,
    )
    ctx = await start(ctx, handle)
    _contexts[tenant_id] = ctx
    return {
        "state": ctx.state.value,
        "inventory": asdict(ctx.inventory) if ctx.inventory else None,
        "history": ctx.history,
    }


@router.post("/objectives")
async def post_objectives(
    req: ObjectiveRequest, scope: TenantScope = Depends(require_admin)
) -> dict:
    tenant_id = scope.tenant_id
    ctx = _ctx_for(tenant_id)
    vertical = VerticalContext(
        industry=req.industry,
        employee_count=req.employee_count,
        venues_or_locations=req.venues_or_locations,
        regulated=req.regulated,
    )
    objectives = []
    for o in req.objectives:
        text = o.get("objective") or o.get("text") or o.get("description")
        if not text:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "each objective must have 'objective' (or 'text' / 'description') field",
            )
        objectives.append(ClientObjective(objective=text, priority=o.get("priority", "MEDIUM")))
    try:
        ctx = submit_objectives(ctx, vertical, objectives)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    _contexts[tenant_id] = ctx
    return {
        "state": ctx.state.value,
        "recommendations": (
            asdict(ctx.recommendations) if ctx.recommendations else None
        ),
    }


@router.post("/deploy")
async def post_deploy(req: DeployRequest, scope: TenantScope = Depends(require_admin)) -> dict:
    tenant_id = scope.tenant_id
    ctx = _ctx_for(tenant_id)
    try:
        ctx = deploy(ctx, req.agent_ids)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    _contexts[tenant_id] = ctx
    return {"state": ctx.state.value, "deployed_agents": ctx.deployed_agents}
