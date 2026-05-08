"""Contain config backend logic."""
# Constant for payment config.
PAYMENT_CONFIG = {
    "confidence_threshold": 0.7,
    "valid_actions": [
        "track_payment",
        "reconcile",
        "send_reminder",
        "generate_report",
        "check_payment_status",
        "refund",
        "capture_payment",
        "cancel_payment",
        "handle_dispute",
    ],
    "default_currency": "USD",
    "reminder_intervals_days": [7, 14, 21],
    "match_accuracy_target": 0.99,
    "supported_gateways": ["stripe", "paypal", "bank_transfer"],
    "report_frequency": "weekly",
    "refund_approval_threshold": 500.0,
    "capture_approval_threshold": 1000.0,
    "approval_ttl_seconds": 300,
    "dispute_auto_escalate": True,
}