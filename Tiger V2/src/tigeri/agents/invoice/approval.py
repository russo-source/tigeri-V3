from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ApprovalDecision:
    decided: bool
    approved: bool
    approver: str
    reason: str


@dataclass
class ApprovalMatrix:
    """Slice 1 deterministic matrix. Real tenant matrices land in a future slice."""

    auto_approve_below: Decimal = Decimal("500")
    manager_threshold: Decimal = Decimal("5000")
    director_threshold: Decimal = Decimal("50000")

    def evaluate(self, amount: Decimal) -> ApprovalDecision:
        if amount <= self.auto_approve_below:
            return ApprovalDecision(True, True, "system:auto", f"≤ {self.auto_approve_below}")
        if amount <= self.manager_threshold:
            return ApprovalDecision(True, True, "role:manager", f"≤ {self.manager_threshold}")
        if amount <= self.director_threshold:
            return ApprovalDecision(True, True, "role:director", f"≤ {self.director_threshold}")
        return ApprovalDecision(False, False, "role:cfo", "manual approval required")
