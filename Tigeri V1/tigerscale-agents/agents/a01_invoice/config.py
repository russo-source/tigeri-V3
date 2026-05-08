"""Contain config backend logic."""
INVOICE_CONFIG: dict = {
    "confidence_threshold": 0.7,
    "required_fields": ["vendor", "amount"],
    "default_currency": "USD",
    "accounting_code": "200",
    "max_invoices_per_day": 80,
    "valid_actions": [
        "create",
        "send",
        "track",
        "remind",
        "mark_paid",
        "list_invoices",
        "check_overdue",
        "approve",
        "approve_all",
        "edit",
    ],
}

PO_CONFIG: dict = {
    "confidence_threshold": 0.7,
    "valid_actions": [
        "create",
        "find",
        "list",
        "edit",
        "approve",
        "send",
        "track",
        "remind",
        "check_overdue",
        "mark_received",
    ],
}

BILL_CONFIG: dict = {
    "confidence_threshold": 0.7,
    "valid_actions": [
        "create",
        "list",
        "find",
        "track",
        "edit",
        "check_overdue",
    ],
}