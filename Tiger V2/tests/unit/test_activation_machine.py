import pytest

from tigeri.activation.discovery import CRMHandle
from tigeri.activation.machine import (
    ActivationContext,
    deploy,
    start,
    submit_objectives,
)
from tigeri.activation.reasoning import ClientObjective, VerticalContext
from tigeri.activation.states import ActivationState


@pytest.mark.asyncio
async def test_unreachable_crm_transitions_to_failure():
    ctx = ActivationContext(tenant_id="tnt_a")
    handle = CRMHandle(source_system="legacy_crm", api_base_url=None)
    ctx = await start(ctx, handle)
    assert ctx.state == ActivationState.S_FAIL_NO_CRM


def test_deploy_requires_s6():
    ctx = ActivationContext(tenant_id="tnt_b", state=ActivationState.S0_SIGNED_IN)
    with pytest.raises(ValueError):
        deploy(ctx, ["invoice_agent"])


def test_objectives_require_s4():
    ctx = ActivationContext(tenant_id="tnt_c", state=ActivationState.S0_SIGNED_IN)
    with pytest.raises(ValueError):
        submit_objectives(
            ctx,
            VerticalContext("retail", 50, 3, False),
            [ClientObjective("automate AP", "HIGH")],
        )
