from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agent_card.registry import get_registry
from tigeri.agents.admin.agent import AdminAgent, TemplateNotFoundError
from tigeri.agents.admin.schemas import AdminInput, AdminOutput
from tigeri.agents.base import AgentRunContext
from tigeri.agents.booking.agent import BookingAgent
from tigeri.agents.booking.schemas import BookingInput, BookingOutput
from tigeri.agents.client_onboarding.agent import ClientOnboardingAgent
from tigeri.agents.client_onboarding.schemas import COInput, COOutput
from tigeri.agents.contract_management.agent import ContractManagementAgent
from tigeri.agents.contract_management.schemas import ContractInput, ContractOutput
from tigeri.agents.expense.agent import ExpenseAgent
from tigeri.agents.expense.schemas import ExpenseInput, ExpenseOutput
from tigeri.agents.financial_reporting.agent import FinancialReportingAgent
from tigeri.agents.financial_reporting.schemas import FRInput, FROutput
from tigeri.agents.invoice.agent import InvoiceAgent
from tigeri.agents.invoice.graph_agent import InvoiceGraphAgent
from tigeri.agents.invoice.schemas import InvoiceInput, InvoiceOutput
from tigeri.agents.staffing.agent import StaffingAgent
from tigeri.agents.staffing.schemas import StaffingInput, StaffingOutput
from tigeri.api.deps import get_session
from tigeri.auth.scope import TenantScope, get_scope

router = APIRouter(prefix="/agents", tags=["agents"])


def _check_tenant(tenant_id: str, body_tenant_id: str) -> None:
    if body_tenant_id != tenant_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "tenant_id in body does not match the authenticated tenant",
        )


@router.get("/{agent_id}/card")
async def get_card(agent_id: str) -> dict:
    """Agent metadata is public — no auth required."""
    try:
        card = get_registry().get(agent_id)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return card.model_dump(mode="json")


@router.get("")
async def list_cards() -> list[dict]:
    """Catalog listing is public — no auth required."""
    return [c.model_dump(mode="json") for c in get_registry().all()]


_invoice_graph_singleton: InvoiceGraphAgent | None = None


def _invoice_graph() -> InvoiceGraphAgent:
    """One InvoiceGraphAgent per process so the in-memory checkpointer is shared
    across requests and session memory accumulates across calls."""

    global _invoice_graph_singleton
    if _invoice_graph_singleton is None:
        _invoice_graph_singleton = InvoiceGraphAgent()
    return _invoice_graph_singleton


@router.post("/invoice_agent/invoke", response_model=InvoiceOutput)
async def invoke_invoice(
    request: InvoiceInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
    x_tigeri_engine: str = Header(default="graph", alias="X-Tigeri-Engine"),
) -> InvoiceOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    if x_tigeri_engine.lower() == "legacy":
        return await InvoiceAgent().invoke(session, ctx, request)
    return await _invoice_graph().invoke(
        session,
        ctx,
        request,
        session_id=x_tigeri_session_id,
        user_id=scope.user_id,
    )


@router.post("/expense_agent/invoke", response_model=ExpenseOutput)
async def invoke_expense(
    request: ExpenseInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> ExpenseOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    agent = ExpenseAgent()
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await agent.invoke(session, ctx, request)


@router.post("/admin_agent/invoke", response_model=AdminOutput)
async def invoke_admin(
    request: AdminInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> AdminOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    agent = AdminAgent()
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    try:
        return await agent.invoke(session, ctx, request)
    except TemplateNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow_template_id not found: {e}") from e


@router.post("/staffing_agent/invoke", response_model=StaffingOutput)
async def invoke_staffing(
    request: StaffingInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> StaffingOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    agent = StaffingAgent()
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await agent.invoke(session, ctx, request)


@router.post("/booking_agent/invoke", response_model=BookingOutput)
async def invoke_booking(
    request: BookingInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
) -> BookingOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    agent = BookingAgent()
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await agent.invoke(session, ctx, request)


# ---- Phase 1 priorities 6-8 (LangGraph-native) ----------------------------

_fr_singleton: FinancialReportingAgent | None = None
_contract_singleton: ContractManagementAgent | None = None
_onboarding_singleton: ClientOnboardingAgent | None = None


def _fr() -> FinancialReportingAgent:
    global _fr_singleton
    if _fr_singleton is None:
        _fr_singleton = FinancialReportingAgent()
    return _fr_singleton


def _contract() -> ContractManagementAgent:
    global _contract_singleton
    if _contract_singleton is None:
        _contract_singleton = ContractManagementAgent()
    return _contract_singleton


def _onboarding() -> ClientOnboardingAgent:
    global _onboarding_singleton
    if _onboarding_singleton is None:
        _onboarding_singleton = ClientOnboardingAgent()
    return _onboarding_singleton


@router.post("/financial_reporting_agent/invoke", response_model=FROutput)
async def invoke_financial_reporting(
    request: FRInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> FROutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await _fr().invoke(
        session, ctx, request, session_id=x_tigeri_session_id, user_id=scope.user_id
    )


@router.post("/contract_management_agent/invoke", response_model=ContractOutput)
async def invoke_contract_management(
    request: ContractInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> ContractOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await _contract().invoke(
        session, ctx, request, session_id=x_tigeri_session_id, user_id=scope.user_id
    )


@router.post("/client_onboarding_agent/invoke", response_model=COOutput)
async def invoke_client_onboarding(
    request: COInput,
    scope: TenantScope = Depends(get_scope),
    session: AsyncSession = Depends(get_session),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> COOutput:
    _check_tenant(scope.tenant_id, request.tenant_id)
    ctx = AgentRunContext.new(tenant_id=scope.tenant_id, actor=f"user:{scope.user_id}")
    return await _onboarding().invoke(
        session, ctx, request, session_id=x_tigeri_session_id, user_id=scope.user_id
    )
