"""Contain agent backend logic."""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import date
import redis as redis_lib
from agents.base_agent import BaseAgent
from agents.a04_payment.tools import (
    parse_payment_message,
    validate_payment,
    format_payment_confirmation_llm,
    match_payment_to_invoice,
    resolve_gateway,
    send_approval_request,
    check_approval_status,
)
from agents.a04_payment.config import PAYMENT_CONFIG
from agents.a04_payment.prompts import PAYMENT_AGENT_PROMPT
from config.db_pool import get_conn
from config.settings import settings
from core.context_builder import build_context, format_for_llm
from integrations.resilience import CircuitBreaker, CircuitOpenError
from memory.agent_memory import save_memory, recall_memory
from memory.rag import retrieve_knowledge
from security.audit import log_action

logger = logging.getLogger(__name__)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
_DEFAULT_CURRENCY = PAYMENT_CONFIG["default_currency"]

_MSG_UNAVAILABLE  = "The payment integration is temporarily unavailable. Please try again in a few minutes."
_MSG_GENERIC_ERR  = "Something went wrong — please try again or contact support."
_MSG_NO_APPROVER  = "This action requires approval but approver access isn't configured. Please contact your admin."


def _redis_has_pending(client_id: str, task_id: str) -> bool:
    """Check if an approval request or result already exists in Redis for this task."""
    return bool(
        _redis.exists(f"approval:pending:{client_id}:{task_id}") or
        _redis.exists(f"approval:result:{client_id}:{task_id}")
    )


class PaymentAgent(BaseAgent):

    """Represent the PaymentAgent component and its related behavior."""
    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        self.confidence_threshold = PAYMENT_CONFIG["confidence_threshold"]
        self._payment_cb = CircuitBreaker(f"payment:{client_id}")

    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return PAYMENT_AGENT_PROMPT

    def _run(self, task: dict) -> dict:
        """Run the requested operation."""
        message = task.get("message", "")
        task_id = task.get("task_id") or hashlib.sha256(
            f"{self.client_id}:{message}".encode()
        ).hexdigest()[:16]
        idempotency_key = hashlib.sha256(f"{self.client_id}:{message}".encode()).hexdigest()
        sender_channel  = task.get("channel", "telegram")

        try:
            data = parse_payment_message(message)
        except Exception as exc:
            logger.error("parse_payment_message failed client=%s: %s", self.client_id, exc)
            result = {"status": "error", "message": "Something went wrong reading your request — please try again."}
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message="parse_payment_message raised")
            return result

        is_valid, reason = validate_payment(data)
        if not is_valid:
            logger.error("Validation failed client=%s: %s", self.client_id, reason)
            result = {"status": "error", "message": reason}
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message=f"Validation failed — {reason}")
            return result

        payer  = data.get("payer", "")
        memory = recall_memory(self.client_id, "a04_payment", message)
        knowledge = retrieve_knowledge(self.client_id, message, "payment")
        context = build_context(
            task=message, memory=memory, knowledge=knowledge,
            client_id=self.client_id, entity=payer,
        )

        try:
            raw      = self.call_llm(task=format_for_llm(context), intent="payment")
            llm_data = self.parse_llm_json(raw)
        except json.JSONDecodeError:
            logger.error("LLM parse failed client=%s", self.client_id)
            result = {"status": "error", "message": "Could not parse payment data — please try again."}
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message="LLM parse failed")
            return result
        except Exception as exc:
            logger.error("LLM call failed client=%s: %s", self.client_id, exc)
            result = {"status": "error", "message": "Request processing failed — please try again."}
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message=f"LLM call failed — {exc}")
            return result

        for key, value in llm_data.items():
            if value is not None and not data.get(key):
                data[key] = value

        data["idempotency_key"] = idempotency_key
        confidence = float(data.get("confidence", 0.0))

        if confidence < self.confidence_threshold:
            result = {
                "status":  "escalate",
                "message": "I need a bit more detail — could you provide the amount, payer, and reference?",
                "raw":     data,
            }
            log_action(self.client_id, "a04_payment", "payment", message, result, "escalate",
                       message=f"Escalated — low confidence ({confidence:.2f})")
            return result

        action = data.get("action", "track_payment")

        if action in ("refund", "capture_payment", "cancel_payment", "handle_dispute"):
            return self._run_with_approval(action, data, task_id, message, sender_channel)

        result_data = self._execute_action(action, data)

        if result_data.get("error"):
            logger.error("Action %s failed client=%s: %s", action, self.client_id, result_data["error"])
            result = {
                "status":  "error",
                "message": f"Could not complete your request right now. Please try again or contact support.",
            }
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message=f"{action} failed — {result_data['error']}")
            return result

        self.record_entity(
            entity_name=payer,
            domain="payment",
            amount=float(data.get("amount") or 0),
            currency=data.get("currency", _DEFAULT_CURRENCY),
        )

        try:
            save_memory(
                self.client_id, "a04_payment",
                f"{action} from {payer} amount {data.get('amount')} "
                f"{data.get('currency', _DEFAULT_CURRENCY)}",
            )
        except Exception as exc:
            logger.warning("save_memory non-fatal client=%s: %s", self.client_id, exc)

        result = {
            "status":  "success",
            "message": format_payment_confirmation_llm(action, data, result_data),
            "action":  action,
            "result":  result_data,
        }
        log_action(
            self.client_id, "a04_payment", "payment", message, result, "success",
            message=f"{action} from {payer} — {data.get('currency', 'USD')} {data.get('amount')}",
        )
        return result

    def _run_with_approval(
        self,
        action: str,
        data: dict,
        task_id: str,
        message: str,
        sender_channel: str = "telegram",
    ) -> dict:
        """Run with approval."""
        if _redis_has_pending(self.client_id, task_id):
            status = check_approval_status(self.client_id, task_id)

            if status == "approved":
                result_data = self._execute_action(action, data)
                if result_data.get("error"):
                    logger.error(
                        "Post-approval action %s failed client=%s: %s",
                        action, self.client_id, result_data["error"],
                    )
                    result = {
                        "status":  "error",
                        "message": _MSG_GENERIC_ERR,
                    }
                    log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                               message=f"{action} failed post-approval — {result_data['error']}")
                    return result

                payer = data.get("payer", "")
                self.record_entity(
                    entity_name=payer,
                    domain="payment",
                    amount=float(data.get("amount") or 0),
                    currency=data.get("currency", _DEFAULT_CURRENCY),
                )
                try:
                    save_memory(
                        self.client_id, "a04_payment",
                        f"{action} approved — {payer} {data.get('currency', 'USD')} {data.get('amount')}",
                    )
                except Exception as exc:
                    logger.warning("save_memory non-fatal client=%s: %s", self.client_id, exc)

                result = {
                    "status":  "success",
                    "message": format_payment_confirmation_llm(action, data, result_data),
                    "action":  action,
                    "result":  result_data,
                }
                log_action(
                    self.client_id, "a04_payment", "payment", message, result, "success",
                    message=f"{action} approved — {data.get('currency', 'USD')} {data.get('amount')}",
                )
                return result

            if status == "rejected":
                result = {
                    "status":  "rejected",
                    "message": f"The {action.replace('_', ' ')} was not approved.",
                }
                log_action(self.client_id, "a04_payment", "payment", message, result, "rejected",
                           message=f"{action} rejected by approver")
                return result

            if status == "pending":
                return {
                    "status":  "pending_approval",
                    "message": "Still waiting for approval — your approver has been notified.",
                    "task_id": task_id,
                }

            logger.warning(
                "Approval status '%s' for task=%s client=%s — re-sending request",
                status, task_id, self.client_id,
            )

        sent = send_approval_request(self.client_id, action, data, task_id, sender_channel)
        if not sent:
            result = {
                "status":  "error",
                "message": _MSG_NO_APPROVER,
            }
            log_action(self.client_id, "a04_payment", "payment", message, result, "error",
                       message=f"{action} — no approver configured")
            return result

        result = {
            "status":  "pending_approval",
            "message": format_payment_confirmation_llm(action, data, {"pending": True}),
            "task_id": task_id,
        }
        log_action(
            self.client_id, "a04_payment", "payment", message, result, "pending",
            message=f"{action} pending approval — {data.get('currency', 'USD')} {data.get('amount')}",
        )
        return result

    def _execute_action(self, action: str, data: dict) -> dict:
        """Execute execute action for PaymentAgent."""
        handler = getattr(self, f"_action_{action}", None)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        try:
            return self._payment_cb.call(handler, data)
        except CircuitOpenError:
            logger.warning(
                "Circuit breaker open during action=%s client=%s", action, self.client_id
            )
            return {"error": _MSG_UNAVAILABLE}
        except Exception as exc:
            logger.error("Action %s failed client=%s: %s", action, self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_track_payment(self, data: dict) -> dict:
        """Execute action track payment for PaymentAgent."""
        match = match_payment_to_invoice(
            client_id=self.client_id,
            payment_amount=float(data.get("amount") or 0),
            payment_ref=data.get("payment_ref", ""),
            payer=data.get("payer", ""),
        )
        saved = self._save_to_db_atomic(data, {"match": match})
        if not saved:
            return {"status": "duplicate"}

        if match is None:
            self._notify_mismatch(data)
            return {"tracked": True, "match": None, "requires_review": True}

        invoice_amount = float(match.get("invoice_amount", 0))
        payment_amount = float(data.get("amount") or 0)
        diff = payment_amount - invoice_amount

        if diff > 0:
            return self._action_mark_overpayment({**data, "overpayment_amount": diff, "match": match})
        if diff < 0:
            return self._action_mark_partial({**data, "partial_amount": payment_amount, "match": match})

        self._mark_invoice_paid_in_accounting(match, data)
        return {"tracked": True, "match": match, "requires_review": False, "status": "fully_paid"}

    def _action_reconcile(self, data: dict) -> dict:
        """Execute action reconcile for PaymentAgent."""
        invoice_ref = data.get("invoice_ref")
        payment_ref = data.get("payment_ref")
        if not invoice_ref or not payment_ref:
            return {"error": "invoice_ref and payment_ref required"}
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE invoices SET status='paid' WHERE client_id=%s AND invoice_number=%s "
                    "RETURNING id, external_id, amount",
                    (self.client_id, invoice_ref),
                )
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"error": f"Invoice {invoice_ref} not found"}

            invoice_id, xero_invoice_id, db_amount = row

            if xero_invoice_id:
                from integrations.accounting_factory import get_system_from_config
                accounting = get_system_from_config(self.client_id)
                try:
                    inv = accounting.get_invoice(xero_invoice_id)
                    if inv.get("Status") == "DRAFT":
                        logger.info(
                            "Auto-authorising DRAFT invoice %s before reconcile client=%s",
                            xero_invoice_id, self.client_id,
                        )
                        accounting.mark_invoice_authorised(xero_invoice_id)
                except Exception as exc:
                    logger.warning(
                        "Pre-reconcile authorise check failed client=%s invoice=%s: %s",
                        self.client_id, xero_invoice_id, exc,
                    )

                try:
                    accounting.mark_invoice_paid(
                        xero_invoice_id,
                        float(db_amount) if db_amount is not None else float(data.get("amount") or 0),
                        date.today().strftime("%Y-%m-%d"),
                    )
                except Exception as exc:
                    logger.error(
                        "Accounting mark_paid failed during reconcile client=%s invoice=%s: %s",
                        self.client_id, xero_invoice_id, exc,
                    )
                    return {
                        "reconciled": True,
                        "invoice_ref": invoice_ref,
                        "payment_ref": payment_ref,
                        "accounting_warning": "Reconciled in DB but accounting sync failed — will retry automatically.",
                    }

            return {"reconciled": True, "invoice_ref": invoice_ref, "payment_ref": payment_ref}
        except Exception as exc:
            logger.error("Reconcile failed client=%s: %s", self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_send_reminder(self, data: dict) -> dict:
        """Execute action send reminder for PaymentAgent."""
        payer_email = data.get("payer_email")
        payer       = data.get("payer")
        invoice_ref = data.get("invoice_ref")

        if not invoice_ref and payer:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT invoice_number, amount, currency, raw_message FROM invoices "
                        "WHERE client_id=%s AND vendor ILIKE %s AND status NOT IN ('paid','cancelled') "
                        "ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{payer}%"),
                    )
                    row = cur.fetchone()
                    cur.close()
                if row:
                    invoice_ref = row[0]
                    data["invoice_ref"] = invoice_ref
                    data["amount"]   = data.get("amount") or str(row[1])
                    data["currency"] = data.get("currency") or row[2]
                    raw = json.loads(row[3]) if row[3] else {}
                    payer_email = payer_email or raw.get("recipient_email")
            except Exception as exc:
                logger.error("Payer lookup failed client=%s: %s", self.client_id, exc)

        if not invoice_ref:
            return {"error": f"No outstanding invoice found for '{payer or 'unknown'}' — please provide the invoice number"}
        if not payer_email:
            return {"error": f"Found invoice {invoice_ref} but no email on file — please provide the recipient email"}

        try:
            from integrations.email_factory import get_email_from_config
            email = get_email_from_config(self.client_id)
            sent  = email.send(
                recipient=payer_email,
                subject=f"Payment Reminder — Invoice {invoice_ref}",
                body=(
                    f"This is a reminder that payment of {data.get('currency', 'USD')} {data.get('amount')} "
                    f"for invoice {invoice_ref} is outstanding. "
                    f"Please arrange payment at your earliest convenience."
                ),
            )
            if sent:
                self._increment_reminder_count(invoice_ref)
            return {"reminder_sent": sent, "payer": payer, "recipient": payer_email}
        except Exception as exc:
            logger.error("Reminder failed client=%s: %s", self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_generate_report(self, data: dict) -> dict:
        """Execute action generate report for PaymentAgent."""
        from datetime import datetime
        report_type = data.get("report_type", "cash_flow")
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if report_type == "ageing":
                    cur.execute(
                        "SELECT invoice_number, vendor, amount, currency, due_date, status, "
                        "CURRENT_DATE - due_date AS days_overdue FROM invoices "
                        "WHERE client_id=%s AND status NOT IN ('paid','cancelled') AND due_date IS NOT NULL "
                        "ORDER BY due_date ASC",
                        (self.client_id,),
                    )
                    rows   = cur.fetchall()
                    report = {
                        "type":          "ageing",
                        "generated_at":  datetime.now().isoformat(),
                        "items": [
                            {
                                "invoice_number": r[0], "vendor": r[1], "amount": str(r[2]),
                                "currency": r[3], "due_date": str(r[4]),
                                "status": r[5], "days_overdue": r[6],
                            }
                            for r in rows
                        ],
                        "total_outstanding": str(sum(float(r[2]) for r in rows)),
                    }
                else:
                    cur.execute(
                        "SELECT COALESCE(SUM(CASE WHEN status='paid' THEN amount ELSE 0 END), 0), "
                        "COALESCE(SUM(CASE WHEN status!='paid' THEN amount ELSE 0 END), 0), "
                        "COUNT(*), COUNT(CASE WHEN status='paid' THEN 1 END), "
                        "COUNT(CASE WHEN status='overdue' THEN 1 END) "
                        "FROM invoices WHERE client_id=%s",
                        (self.client_id,),
                    )
                    row    = cur.fetchone()
                    report = {
                        "type":              "cash_flow",
                        "generated_at":      datetime.now().isoformat(),
                        "total_received":    str(row[0]),
                        "total_outstanding": str(row[1]),
                        "total_invoices":    row[2],
                        "paid_count":        row[3],
                        "overdue_count":     row[4],
                    }
                cur.close()
            return {"report_generated": True, "report": report}
        except Exception as exc:
            logger.error("Report generation failed client=%s: %s", self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_mark_overpayment(self, data: dict) -> dict:
        """Execute action mark overpayment for PaymentAgent."""
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE payments SET status='overpaid' WHERE client_id=%s AND idempotency_key=%s",
                    (self.client_id, data.get("idempotency_key")),
                )
                cur.close()
            self._notify_mismatch(
                data,
                f"Overpayment of {data.get('currency', 'USD')} {data.get('overpayment_amount')} detected",
            )
            return {
                "overpayment": True,
                "overpayment_amount": data.get("overpayment_amount"),
                "requires_review": True,
            }
        except Exception as exc:
            logger.error("Mark overpayment failed client=%s: %s", self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_mark_partial(self, data: dict) -> dict:
        """Execute action mark partial for PaymentAgent."""
        match = data.get("match", {})
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE payments SET status='partial' WHERE client_id=%s AND idempotency_key=%s",
                    (self.client_id, data.get("idempotency_key")),
                )
                if match.get("invoice_id"):
                    cur.execute(
                        "UPDATE invoices SET status='partial' WHERE id=%s AND client_id=%s",
                        (match["invoice_id"], self.client_id),
                    )
                cur.close()
            self._notify_mismatch(
                data,
                f"Partial payment of {data.get('currency', 'USD')} {data.get('partial_amount')} received",
            )
            return {
                "partial": True,
                "partial_amount": data.get("partial_amount"),
                "requires_review": True,
            }
        except Exception as exc:
            logger.error("Mark partial failed client=%s: %s", self.client_id, exc)
            return {"error": _MSG_GENERIC_ERR}

    def _action_check_payment_status(self, data: dict) -> dict:
        """Execute action check payment status for PaymentAgent."""
        gateway = resolve_gateway(data, self.client_id)
        if not gateway:
            return {"error": "No gateway resolved — bank transfer payments cannot be queried directly"}
        return gateway.check_payment_status(data.get("payment_ref", ""))

    def _action_refund(self, data: dict) -> dict:
        """Execute action refund for PaymentAgent."""
        gateway = resolve_gateway(data, self.client_id)
        if not gateway:
            return {"error": "Refunds can only be processed for Stripe or PayPal payments"}

        payment_ref = data.get("payment_ref", "")
        amount      = float(data.get("amount") or 0) or None
        reason      = data.get("notes", "requested_by_customer")

        if data.get("payment_method") == "paypal":
            capture_id = self._get_paypal_capture_id(payment_ref)
            if not capture_id:
                return {"error": f"Could not find PayPal capture ID for order {payment_ref}"}
            result = gateway.refund(capture_id, amount=amount, reason=reason)  # type: ignore
        else:
            result = gateway.refund(payment_ref, amount=amount, reason=reason)  # type: ignore

        if not result.get("error"):
            self._mark_payment_refunded(data, result)
        return result

    def _action_capture_payment(self, data: dict) -> dict:
        """Execute action capture payment for PaymentAgent."""
        gateway = resolve_gateway(data, self.client_id)
        if not gateway:
            return {"error": "Capture only supported for Stripe or PayPal payments"}
        payment_ref = data.get("payment_ref", "")
        if data.get("payment_method") == "paypal":
            return gateway.capture_order(payment_ref)  # type: ignore
        return gateway.capture_payment(  # type: ignore
            payment_ref,
            amount_to_capture=float(data.get("amount") or 0) or None,
        )

    def _action_cancel_payment(self, data: dict) -> dict:
        """Execute action cancel payment for PaymentAgent."""
        gateway = resolve_gateway(data, self.client_id)
        if not gateway:
            return {"error": "Cancel only supported for Stripe or PayPal payments"}
        payment_ref = data.get("payment_ref", "")
        if data.get("payment_method") == "paypal":
            return gateway.cancel_order(payment_ref)  # type: ignore
        return gateway.cancel_payment(  # type: ignore
            payment_ref,
            reason=data.get("notes", "requested_by_customer"),
        )

    def _action_handle_dispute(self, data: dict) -> dict:
        """Execute action handle dispute for PaymentAgent."""
        gateway = resolve_gateway(data, self.client_id)
        if not gateway:
            return {"error": "Dispute handling only supported for Stripe or PayPal payments"}
        dispute_id = data.get("dispute_id", "")
        dispute    = gateway.get_dispute(dispute_id)  # type: ignore
        if dispute.get("error"):
            return dispute
        self._notify_mismatch(
            data,
            f"Dispute opened — reason: {dispute.get('reason')} — due by: {dispute.get('due_by')}",
        )
        log_action(
            self.client_id, "a04_payment", "dispute", dispute_id, dispute, "escalate",
            message=f"Dispute flagged — {dispute.get('reason')}",
        )
        return dispute

    def _save_to_db_atomic(self, data: dict, result_data: dict) -> bool:
        """Execute save to db atomic for PaymentAgent."""
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO payments (client_id, payment_ref, payer, amount, currency, "
                    "payment_method, status, idempotency_key, raw_message) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (
                        self.client_id,
                        data.get("payment_ref"),
                        data.get("payer"),
                        data.get("amount"),
                        data.get("currency", _DEFAULT_CURRENCY),
                        data.get("payment_method"),
                        "processed",
                        data.get("idempotency_key"),
                        json.dumps(data),
                    ),
                )
                row = cur.fetchone()
                if row:
                    match = result_data.get("match")
                    if match and match.get("invoice_id"):
                        cur.execute(
                            "UPDATE invoices SET status='paid' "
                            "WHERE id=%s AND client_id=%s AND status != 'paid'",
                            (match["invoice_id"], self.client_id),
                        )
                cur.close()
                return row is not None
        except Exception as exc:
            logger.error("Atomic DB save failed client=%s: %s", self.client_id, exc)
            raise

    def _mark_invoice_paid_in_accounting(self, match: dict, data: dict) -> None:
        """Execute mark invoice paid in accounting for PaymentAgent."""
        try:
            from integrations.accounting_factory import get_system_from_config
            accounting      = get_system_from_config(self.client_id)
            xero_invoice_id = match.get("xero_invoice_id")

            if xero_invoice_id and hasattr(accounting, "mark_invoice_paid"):
                try:
                    inv = accounting.get_invoice(xero_invoice_id)
                    if inv.get("Status") == "DRAFT":
                        logger.info(
                            "Auto-authorising DRAFT invoice %s before payment client=%s",
                            xero_invoice_id, self.client_id,
                        )
                        accounting.mark_invoice_authorised(xero_invoice_id)
                except Exception as exc:
                    logger.warning(
                        "Pre-payment authorise check failed client=%s invoice=%s: %s",
                        self.client_id, xero_invoice_id, exc,
                    )

                accounting.mark_invoice_paid(
                    xero_invoice_id,
                    float(data.get("amount") or 0),
                    date.today().strftime("%Y-%m-%d"),
                )

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE invoices SET status='paid' WHERE id=%s AND client_id=%s",
                    (match["invoice_id"], self.client_id),
                )
                cur.close()
        except Exception as exc:
            logger.error(
                "mark_invoice_paid_in_accounting failed client=%s invoice=%s: %s",
                self.client_id, match.get("invoice_id"), exc,
            )

    def _get_paypal_capture_id(self, order_id: str) -> str | None:
        """Return paypal capture id."""
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT metadata->>'capture_id' FROM payments "
                    "WHERE client_id=%s AND payment_ref=%s LIMIT 1",
                    (self.client_id, order_id),
                )
                row = cur.fetchone()
                cur.close()
            return row[0] if row and row[0] else None
        except Exception as exc:
            logger.error("_get_paypal_capture_id failed client=%s: %s", self.client_id, exc)
            return None

    def _mark_payment_refunded(self, data: dict, refund_result: dict) -> None:
        """Execute mark payment refunded for PaymentAgent."""
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE payments SET status='refunded', "
                    "metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb "
                    "WHERE client_id=%s AND payment_ref=%s",
                    (
                        json.dumps({
                            "refund_id":       refund_result.get("refund_id"),
                            "refunded_amount": refund_result.get("amount"),
                        }),
                        self.client_id,
                        data.get("payment_ref"),
                    ),
                )
                cur.close()
        except Exception as exc:
            logger.error("_mark_payment_refunded failed client=%s: %s", self.client_id, exc)

    def _notify_mismatch(
        self,
        data: dict,
        reason: str = "Payment could not be matched to an invoice",
    ) -> None:
        """Execute notify mismatch for PaymentAgent."""
        try:
            from config.client_config import get_client_config
            config         = get_client_config(self.client_id)
            approver_email = config.get("approve_email")

            user_message = (
                f"A payment of {data.get('currency', 'USD')} {data.get('amount')} "
                f"from {data.get('payer', 'unknown')} requires manual review.\n"
                f"Reference: {data.get('payment_ref') or 'N/A'}\n"
                f"Reason: {reason}"
            )

            if not approver_email:
                from core.alerting import send_client_telegram_alert
                send_client_telegram_alert(self.client_id, user_message)
                return

            from integrations.email_factory import get_email_from_config
            email = get_email_from_config(self.client_id)
            email.send(
                recipient=approver_email,
                subject=f"Payment Review Required — {data.get('payment_ref', 'N/A')}",
                body=user_message,
            )
        except Exception as exc:
            logger.error("_notify_mismatch failed client=%s: %s", self.client_id, exc)

    def _increment_reminder_count(self, invoice_ref: str | None) -> None:
        """Execute increment reminder count for PaymentAgent."""
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE invoices SET reminder_count=reminder_count+1, reminder_sent_at=NOW() "
                    "WHERE client_id=%s AND invoice_number=%s",
                    (self.client_id, invoice_ref),
                )
                cur.close()
        except Exception as exc:
            logger.error("Reminder count update failed client=%s: %s", self.client_id, exc)