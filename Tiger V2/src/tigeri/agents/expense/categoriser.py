"""Tenant chart-of-accounts categorisation. Slice 2 deterministic stub."""

_KEYWORD_MAP: dict[str, list[str]] = {
    "TRAVEL": ["uber", "lyft", "taxi", "airline", "qantas", "virgin"],
    "MEALS": ["restaurant", "cafe", "coffee", "starbucks"],
    "ACCOMMODATION": ["hotel", "motel", "airbnb"],
    "OFFICE_SUPPLIES": ["officeworks", "staples"],
    "SOFTWARE": ["aws", "github", "openai", "anthropic"],
}


def categorise(merchant: str) -> str:
    needle = merchant.lower()
    for category, keywords in _KEYWORD_MAP.items():
        if any(k in needle for k in keywords):
            return category
    return "UNCATEGORISED"
