from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ExpensePolicy:
    """Slice 2 deterministic policy."""

    per_category_limit: dict[str, Decimal] = field(default_factory=dict)
    restricted_categories: set[str] = field(default_factory=set)
    needs_review_above: Decimal = Decimal("250")

    def evaluate(self, category: str, amount: Decimal) -> tuple[str, str]:
        if category in self.restricted_categories:
            return "OUT_OF_POLICY", f"category {category} is restricted"
        limit = self.per_category_limit.get(category)
        if limit is not None and amount > limit:
            return "OUT_OF_POLICY", f"amount {amount} > category limit {limit}"
        if amount > self.needs_review_above:
            return "NEEDS_REVIEW", f"amount {amount} > review threshold {self.needs_review_above}"
        return "WITHIN_POLICY", "ok"
