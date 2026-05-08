import httpx
import pytest
import respx

from tigeri.activation.discovery import CRMHandle
from tigeri.activation.machine import ActivationContext, deploy, start, submit_objectives
from tigeri.activation.reasoning import ClientObjective, VerticalContext
from tigeri.activation.states import ActivationState


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_with_mcp_then_objectives_then_deploy():
    respx.post("https://mcp.example.test/list_tools").mock(
        return_value=httpx.Response(
            200,
            json={
                "tools": ["read_invoice", "create_invoice"],
                "resources": ["invoice", "customer"],
                "scopes": ["invoices.read", "invoices.write"],
            },
        )
    )

    ctx = ActivationContext(tenant_id="tnt_happy")
    handle = CRMHandle(
        source_system="legacy_crm",
        mcp_endpoint="https://mcp.example.test",
        api_base_url="https://api.example.test",
    )
    ctx = await start(ctx, handle)
    assert ctx.state == ActivationState.S4_OBJECTIVE_INTAKE
    assert ctx.inventory is not None
    assert ctx.inventory.access_mode == "MCP"
    assert "invoice" in ctx.inventory.discovered_objects

    ctx = submit_objectives(
        ctx,
        VerticalContext("logistics", 80, 4, True),
        [ClientObjective("automate vendor invoice processing", "HIGH")],
    )
    assert ctx.state == ActivationState.S6_RECOMMENDATION_REVIEW
    assert ctx.recommendations is not None
    top = ctx.recommendations.ranked_recommendations[0]
    assert top.agent_id == "invoice_agent"
    assert top.projected_roi == "$8K–12K per yr per finance FTE"

    ctx = deploy(ctx, ["invoice_agent"])
    assert ctx.state == ActivationState.S8_ACTIVE
    assert ctx.deployed_agents == ["invoice_agent"]


@pytest.mark.asyncio
@respx.mock
async def test_mcp_failure_falls_back_to_api():
    respx.post("https://mcp.example.test/list_tools").mock(
        return_value=httpx.Response(500)
    )
    respx.get("https://api.example.test/introspect").mock(
        return_value=httpx.Response(
            200,
            json={
                "object_types": ["invoice"],
                "endpoints": ["/v1/invoices"],
                "scopes": ["read"],
            },
        )
    )
    ctx = ActivationContext(tenant_id="tnt_fb")
    handle = CRMHandle(
        source_system="legacy_crm",
        mcp_endpoint="https://mcp.example.test",
        api_base_url="https://api.example.test",
    )
    ctx = await start(ctx, handle)
    assert ctx.state == ActivationState.S4_OBJECTIVE_INTAKE
    assert ctx.inventory is not None
    assert ctx.inventory.access_mode == "API"
