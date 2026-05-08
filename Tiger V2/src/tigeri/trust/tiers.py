from tigeri.agent_card.schema import TrustTier

TIER_DESCRIPTIONS: dict[TrustTier, str] = {
    TrustTier.OBSERVER: (
        "Reads source systems and produces reports only; cannot mutate state. "
        "Suitable for regulated read-only contexts."
    ),
    TrustTier.RECOMMENDER: (
        "Proposes actions for human approval; cannot execute without explicit consent. "
        "Suitable for regulated workflows requiring human-in-the-loop."
    ),
    TrustTier.ACTOR_GATED: (
        "Executes pre-approved actions within configured policy bounds; out-of-bounds "
        "requests escalate to a human approver."
    ),
    TrustTier.ACTOR_ELEVATED: (
        "Executes high-impact actions under tenant-scoped policy with mandatory dual-control "
        "for designated thresholds."
    ),
}

__all__ = ["TrustTier", "TIER_DESCRIPTIONS"]
