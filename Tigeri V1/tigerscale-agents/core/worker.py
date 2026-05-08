"""Contain worker backend logic."""
import logging
import sys
from celery import Celery
from config.settings import settings

logger = logging.getLogger(__name__)
celery_app = Celery(
    "tigerscale",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["core.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=90,  
    task_time_limit=120,
    result_expires=86_400,
 
    task_queues={
        "high":        {"exchange": "high",        "routing_key": "high"},
        "normal":      {"exchange": "normal",       "routing_key": "normal"},
        "low":         {"exchange": "low",          "routing_key": "low"},
        "dead_letter": {"exchange": "dead_letter",  "routing_key": "dead_letter"},
    },
    task_default_queue="normal",
    beat_schedule={
        "beat-heartbeat": {
            "task": "core.tasks.beat_heartbeat",
            "schedule": 60.0,
        },
        "celery-health-check": {
            "task": "core.tasks.celery_health_alert",
            "schedule": 120.0,
        },
        "drain-audit-fallback": {
            "task": "core.tasks.drain_audit_fallback",
            "schedule": 300.0,
        },
        "refresh-oauth-tokens": {
            "task": "core.tasks.refresh_oauth_tokens",
            "schedule": 480.0,
        },
        "webhook-health-check": {
            "task":     "core.tasks.webhook_health_check",
            "schedule": 3600.0,
        },

        "invoice-reminder-sweep": {
            "task": "core.tasks.invoice_reminder_sweep",
            "schedule": 86400.0,
        },
        "document-expiry-sweep": {
            "task": "core.tasks.document_expiry_sweep",
            "schedule": 86400.0,
        },
        "payment-reminder-sweep": {
            "task": "core.tasks.payment_reminder_sweep",
            "schedule": 86400.0,
        },
        "autonomous-overdue-invoice-sweep": {
            "task": "core.tasks.autonomous_overdue_invoice_sweep",
            "schedule": 43200.0,   # every 12 hours
        },
        "autonomous-expense-approval-sweep": {
            "task":     "core.tasks.autonomous_expense_approval_sweep",
            "schedule": 43200.0,   # every 12 hours
        },
        "autonomous-payment-reconcile-sweep": {
            "task":     "core.tasks.autonomous_payment_reconcile_sweep",
            "schedule": 43200.0,   # every 12 hours
        },
        "agent-metrics-report-daily": {
            "task": "core.tasks.metrics_report",
            "schedule": 86400.0,
        },
        "classifier-feedback-weekly": {
            "task": "core.tasks.classifier_feedback",
            "schedule": 604800.0,
        },
        "proactive-insights-hourly": {
            "task": "core.tasks.proactive_insights",
            "schedule": 3600.0,
        },
        "memory-summarization-weekly": {
            "task": "core.tasks.summarize_all_memories",
            "schedule": 604800.0,
        },
        "confidence-tuning-weekly": {
            "task": "core.tasks.tune_confidence_thresholds",
            "schedule": 604800.0,
        },
    },
)

@celery_app.on_after_finalize.connect # type: ignore
def verify_tasks(sender, **kwargs) -> None:
    """Execute verify tasks."""
    required = [
        "core.tasks.run_agent_task",
        "core.tasks.dead_letter_handler",
        "core.tasks.beat_heartbeat",
        "core.tasks.autonomous_overdue_invoice_sweep",
        "core.tasks.autonomous_expense_approval_sweep",
        "core.tasks.autonomous_payment_reconcile_sweep",
    ]
    for name in required:
        if name not in sender.tasks:
            logger.critical("Required task not registered: %s", name)
            print(f"[FATAL] Task not registered: {name}", file=sys.stderr)