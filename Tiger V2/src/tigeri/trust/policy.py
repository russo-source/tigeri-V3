from dataclasses import dataclass
from decimal import Decimal

from tigeri.agent_card.schema import TrustTier


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


@dataclass
class TenantPolicy:
    """Minimal tenant policy used by ACTOR_GATED agents."""

    auto_approve_max_amount: Decimal = Decimal("500")
    elevated_dual_control_threshold: Decimal = Decimal("50000")


def evaluate_actor_gated(
    policy: TenantPolicy,
    amount: Decimal,
) -> PolicyDecision:
    if amount <= policy.auto_approve_max_amount:
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason=f"amount {amount} ≤ auto_approve_max {policy.auto_approve_max_amount}",
        )
    return PolicyDecision(
        allowed=True,
        requires_approval=True,
        reason=f"amount {amount} > auto_approve_max {policy.auto_approve_max_amount}",
    )


def evaluate(
    tier: TrustTier,
    policy: TenantPolicy,
    amount: Decimal | None = None,
) -> PolicyDecision:
    if tier == TrustTier.OBSERVER:
        return PolicyDecision(allowed=True, requires_approval=False, reason="observer tier")
    if tier == TrustTier.RECOMMENDER:
        return PolicyDecision(
            allowed=True, requires_approval=True, reason="recommender tier requires human consent"
        )
    if tier == TrustTier.ACTOR_GATED:
        if amount is None:
            return PolicyDecision(
                allowed=True, requires_approval=False, reason="non-financial actor_gated action"
            )
        return evaluate_actor_gated(policy, amount)
    if tier == TrustTier.ACTOR_ELEVATED:
        if amount is None or amount < policy.elevated_dual_control_threshold:
            return PolicyDecision(
                allowed=True, requires_approval=True, reason="elevated tier requires single approval"
            )
        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            reason=f"amount {amount} ≥ dual-control threshold {policy.elevated_dual_control_threshold}",
        )
    raise ValueError(f"unknown trust tier: {tier}")
