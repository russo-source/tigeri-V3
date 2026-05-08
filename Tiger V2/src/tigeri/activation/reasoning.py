from dataclasses import dataclass, field
from datetime import UTC, datetime

from tigeri.agent_card.registry import get_registry
from tigeri.agent_card.schema import AgentCard
from tigeri.activation.discovery import CapabilityInventory


@dataclass
class VerticalContext:
    industry: str
    employee_count: int
    venues_or_locations: int
    regulated: bool


@dataclass
class ClientObjective:
    objective: str
    priority: str  # HIGH | MEDIUM | LOW


@dataclass
class Recommendation:
    agent_id: str
    rank: int
    match_score: float
    projected_roi: str
    rationale: str
    required_integrations_present: bool


@dataclass
class ReasoningResult:
    """Output of S5 in section 4.3 of the catalog."""

    tenant_id: str
    ranked_recommendations: list[Recommendation] = field(default_factory=list)
    generated_at: str = ""


_OBJECTIVE_KEYWORDS: dict[str, set[str]] = {
    "invoice_agent": {"invoice", "ap", "payable", "vendor bill"},
    "expense_agent": {"expense", "receipt", "reimburse"},
    "admin_agent": {"onboarding", "offboarding", "form", "workflow"},
    "staffing_agent": {"shift", "roster", "schedule", "crew"},
    "booking_agent": {"reservation", "booking", "venue", "meeting"},
    "financial_reporting_agent": {"p&l", "cashflow", "kpi", "board", "report"},
    "contract_management_agent": {"contract", "renewal", "obligation"},
    "client_onboarding_agent": {"client onboarding", "kyc", "kyb", "kickoff"},
}


def _score_agent(card: AgentCard, objectives: list[ClientObjective], inv: CapabilityInventory) -> float:
    """Heuristic scorer used as a deterministic fallback when no LLM is wired.

    The catalog's section 4.3 reasoning step is LLM-driven in production; this
    function gives the slice a tested, deterministic baseline.
    """

    keywords = _OBJECTIVE_KEYWORDS.get(card.agent_id, set())
    if not keywords:
        return 0.0
    score = 0.0
    for obj in objectives:
        text = obj.objective.lower()
        weight = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}.get(obj.priority, 0.3)
        if any(k in text for k in keywords):
            score += weight
    if inv.discovered_objects or inv.discovered_actions:
        score += 0.1
    return min(score, 1.0)


def rank_agents(
    tenant_id: str,
    vertical: VerticalContext,
    inventory: CapabilityInventory,
    objectives: list[ClientObjective],
) -> ReasoningResult:
    cards = get_registry().all()
    scored = []
    for card in cards:
        score = _score_agent(card, objectives, inventory)
        if score <= 0:
            continue
        scored.append((card, score))
    scored.sort(key=lambda t: (-t[1], t[0].priority))

    recs = [
        Recommendation(
            agent_id=card.agent_id,
            rank=idx + 1,
            match_score=round(score, 3),
            projected_roi=card.roi_baseline,
            rationale=(
                f"Matched on objective keywords for {card.name} (score {score:.2f}); "
                f"vertical={vertical.industry}, regulated={vertical.regulated}."
            ),
            required_integrations_present=True,
        )
        for idx, (card, score) in enumerate(scored)
    ]

    return ReasoningResult(
        tenant_id=tenant_id,
        ranked_recommendations=recs,
        generated_at=datetime.now(UTC).isoformat(),
    )
