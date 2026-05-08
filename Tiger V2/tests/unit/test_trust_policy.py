from decimal import Decimal

from tigeri.agent_card.schema import TrustTier
from tigeri.trust.policy import TenantPolicy, evaluate


def test_observer_never_requires_approval():
    decision = evaluate(TrustTier.OBSERVER, TenantPolicy())
    assert decision.allowed
    assert not decision.requires_approval


def test_recommender_always_requires_approval():
    decision = evaluate(TrustTier.RECOMMENDER, TenantPolicy())
    assert decision.requires_approval


def test_actor_gated_auto_approves_below_limit():
    decision = evaluate(TrustTier.ACTOR_GATED, TenantPolicy(), Decimal("100"))
    assert decision.allowed
    assert not decision.requires_approval


def test_actor_gated_requires_approval_above_limit():
    decision = evaluate(TrustTier.ACTOR_GATED, TenantPolicy(), Decimal("9999"))
    assert decision.allowed
    assert decision.requires_approval


def test_actor_elevated_dual_control_above_threshold():
    decision = evaluate(TrustTier.ACTOR_ELEVATED, TenantPolicy(), Decimal("100000"))
    assert decision.requires_approval
    assert "dual-control" in decision.reason
