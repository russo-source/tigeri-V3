"""Contain tasks backend logic."""
import json
import logging
import re as _re
import time

import httpx
import redis as redis_lib
from celery.exceptions import MaxRetriesExceededError

from config.db_pool import get_conn
from config.settings import settings
from core.alerting import send_telegram_alert, send_client_telegram_alert
from core.orchestrator import AGENT_REGISTRY, _handle_general, register_agent, run_agent_task_dispatch
from core.worker import celery_app
from integrations.token_manager import get_stored_token, do_refresh, handle_dead_token
from security.audit import log_action

logger = logging.getLogger(__name__)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

from agents.a01_invoice.agent import InvoiceAgent, BillAgent, POAgent
from agents.a02_expense.agent import ExpenseAgent
from agents.a03_admin.agent   import AdminAgent
from agents.a04_payment.agent import PaymentAgent

register_agent("a01_invoice", InvoiceAgent)
register_agent("a01_po",      POAgent)
register_agent("a02_expense", ExpenseAgent)
register_agent("a03_admin",   AdminAgent)
register_agent("a04_payment", PaymentAgent)

_AGENT_FOR_PLAN = {
    "a01_invoice": InvoiceAgent,
    "a02_expense": ExpenseAgent,
    "a03_admin":   AdminAgent,
    "a04_payment": PaymentAgent,
}

_BILL_KEYWORDS = (
    "list bills", "list all bills", "show bills", "show all bills",
    "view bills", "my bills", "all my bills", "list the bills",
    "check bills", "overdue bills", "pending bills",
    "log bill", "record bill", "add bill", "create bill",
    "find bill", "track bill", "edit bill",
    "vendor bill", "supplier bill", "inbound bill",
    "got a bill", "received a bill",
)
_PAYMENT_KEYWORDS = (
    "payment","pay","paid","invoice paid","reconcile",
    "cash flow","ageing","aging","payout","remittance",
    "outstanding","overdue report","generate report",
)
_ADMIN_KEYWORDS = (
    "folder", "create folder",
    "file this", "file the", "file a ", "file document",
    "store this", "store the", "store document",
    "save this", "save the", "save to",
    "put in drive", "put this in", "add to drive",
    "find document", "find the document", "find contract", "find agreement",
    "find the contract", "find the agreement",
    "list documents", "list all documents", "show documents",
    "list meetings", "show meetings", "list all meetings",
    "upload document", "upload this", "upload the",
    "read this document", "read the document", "read this file",
    "open this", "open the file", "summarise this", "summarize this",
    "schedule meeting", "book meeting", "schedule a meeting", "book a meeting",
    "set up a meeting", "arrange a meeting",
    "send reminder", "meeting reminder", "remind attendees",
    "add attendee", "add guest", "invite to meeting",
    # permits
   "track permit", "track licence", "track license", "track expiry",
    "contract for", "agreement for", "this contract", "this agreement",
    "nda for", "mou for",
)


def _resolve_intent(intent: str, message: str) -> str:
    if intent and intent != "unknown":
        return intent
    lower = message.lower()
    if any(kw in lower for kw in _BILL_KEYWORDS):
        return "bill"
    if any(kw in lower for kw in _PAYMENT_KEYWORDS):
        return "payment"
    if any(kw in lower for kw in _ADMIN_KEYWORDS):
        return "admin"
    return intent


def _is_cb_error(exc: Exception) -> bool:
    return "Circuit breaker open" in str(exc)


def _is_breaker_open(provider: str, client_id: str) -> bool:
    return bool(_redis.exists(f"cb:open:{provider}:{client_id}"))


def _get_accounting_provider(client_id: str) -> str | None:
    try:
        from integrations.integration_resolver import resolve_provider
        return resolve_provider(client_id, "accounting")
    except Exception as e:
        logger.error("_get_accounting_provider failed client=%s: %s", client_id, e)
        return None


def _mark_disconnected(client_id: str, provider: str) -> None:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE client_integrations SET connected=FALSE,updated_at=NOW() "
                "WHERE client_id=%s AND provider=%s",
                (client_id, provider),
            )
            cur.close()
    except Exception as e:
        logger.error("_mark_disconnected failed %s:%s: %s", provider, client_id, e)


def _run_plan_steps(client_id: str, plan, task: dict) -> dict:
    """
    Execute a decomposed Plan sequentially.
    Each step runs agent.run_loop() with the tool input from the plan.
    Step results are passed as context to subsequent dependent steps.
    """
    from core.planner import format_plan_for_log
    logger.info("_run_plan_steps client=%s\n%s", client_id, format_plan_for_log(plan))

    step_results: dict[int, dict] = {}
    last_result:  dict            = {}

    for step in plan.steps:
        agent_cls = _AGENT_FOR_PLAN.get(step.agent)
        if not agent_cls:
            logger.warning("_run_plan_steps unknown agent=%s step=%d", step.agent, step.step)
            continue

        agent = agent_cls(client_id=client_id)

        prior_context = ""
        if step.depends_on and step.depends_on in step_results:
            prior = step_results[step.depends_on]
            prior_context = json.dumps(prior, default=str)[:500]

        step_message = step.reason
        if prior_context:
            step_message = f"{step.reason}\n\nPrevious step result: {prior_context}"

        step_task = {
            **task,
            "message":  step_message,
            "domain":   step.agent.replace("a0", "").replace("_", ""),
            "_plan_tool":  step.tool,
            "_plan_input": step.input,
        }

        try:
            if step.tool and hasattr(agent, "execute_tool"):
                tool_input = {**step.input, **agent._task_meta(task)}
                result = agent.execute_tool(step.tool, tool_input)
            else:
                result = agent.run_loop(step_task)

            step_results[step.step] = result
            last_result = result

            logger.info("_run_plan_steps step=%d tool=%s status=%s",
                        step.step, step.tool, result.get("status", "ok"))

        except Exception as exc:
            logger.error("_run_plan_steps step=%d tool=%s failed client=%s: %s",
                         step.step, step.tool, client_id, exc)
            step_results[step.step] = {"error": str(exc)}
            last_result = {"status": "error", "message": str(exc)}

    return {
        "status":       "success" if not last_result.get("error") else "error",
        "message":      last_result.get("message", plan.summary),
        "plan_summary": plan.summary,
        "steps_run":    len(step_results),
        "result":       last_result,
    }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=2,
                 name="core.tasks.run_agent_task")
def run_agent_task(self, client_id, intent, message, mime_type="",
                   filename="", sender="", channel="telegram",
                   is_document=False, file_bytes_hex=""):
    """Run agent task."""
    intent = _resolve_intent(intent, message)

    if is_document:
        agent_name = run_agent_task_dispatch(
            client_id=client_id,
            intent=intent,
            message=message,
            mime_type=mime_type,
            filename=filename,
            is_document=is_document,
        )
    else:
        agent_name = {
            "invoice": "a01_invoice",
            "bill":    "a01_invoice",
            "po":      "a01_po",
            "expense": "a02_expense",
            "admin":   "a03_admin",
            "payment": "a04_payment",
        }.get(intent)

    if agent_name == "general":
        result = _handle_general(message, client_id)
        _notify_channel(
            client_id=client_id,
            task_id=self.request.id,
            result=result,
            sender=sender,
            channel=channel,
        )
        return result

    if not agent_name:
        return {
            "status": "out_of_scope",
            "message": "I can help with invoices, purchase orders, bills, expenses, payments, and admin tasks.",
        }

    if _redis.exists(f"agent:paused:{client_id}:{agent_name}"):
        return {"status": "paused", "message": "Service temporarily unavailable."}

    import hashlib
    import uuid as _uuid

    if is_document:
        lock_key = f"lock:agent:{client_id}:{intent}:doc:{_uuid.uuid4().hex[:16]}"
    else:
        msg_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
        lock_key = f"lock:agent:{client_id}:{intent}:{msg_hash}"

    file_bytes = bytes.fromhex(file_bytes_hex) if file_bytes_hex else b""

    task_dict = {
        "message":     message,
        "intent":      intent,
        "task_id":     self.request.id,
        "channel":     channel,
        "sender":      sender,
        "sender_id":   sender,
        "mime_type":   mime_type,
        "filename":    filename,
        "is_document": is_document,
        "file_bytes":  file_bytes,
        "image":       file_bytes if (mime_type or "").startswith("image/") and file_bytes else None,
        "media_type":  mime_type  if (mime_type or "").startswith("image/") and file_bytes else None,
    }

    try:
        if not _redis.set(lock_key, "1", nx=True, ex=90):
            return {"status": "duplicate", "message": "Already processing this request."}
        try:
            if not is_document and agent_name in _AGENT_FOR_PLAN:
                try:
                    from core.planner import plan_and_summarise
                    plan, is_multi = plan_and_summarise(
                        message=message, client_id=client_id,
                        context=f"intent={intent} agent={agent_name}",
                    )
                    if is_multi and plan:
                        logger.info("run_agent_task: multi-step plan client=%s steps=%d",
                                    client_id, len(plan.steps))
                        res = _run_plan_steps(client_id, plan, task_dict)
                        _notify_channel(client_id=client_id, task_id=self.request.id,
                                        result=res, sender=sender, channel=channel,
                                        file_bytes=file_bytes, mime_type=mime_type)
                        return res
                except Exception as plan_exc:
                    logger.warning("Planner failed — falling through to single-shot: %s", plan_exc)

            if agent_name == "a01_po":
                agent = POAgent(client_id=client_id)
            elif intent == "bill":
                agent = BillAgent(client_id=client_id)
            elif is_document and agent_name == "a01_invoice":
                agent = BillAgent(client_id=client_id)
            elif agent_name == "a01_invoice":
                agent = InvoiceAgent(client_id=client_id)
            else:
                if agent_name not in AGENT_REGISTRY:
                    return {"status": "error", "message": f"Agent not registered: {agent_name}"}
                agent = AGENT_REGISTRY[agent_name](client_id=client_id)

            res = agent.run(task_dict)
            _notify_channel(
                client_id=client_id,
                task_id=self.request.id,
                result=res,
                sender=sender,
                channel=channel,
                file_bytes=file_bytes,
                mime_type=mime_type,
            )
            return res
        finally:
            _redis.delete(lock_key)

    except Exception as exc:
        if _is_cb_error(exc):
            logger.warning("CB open — no retry client=%s intent=%s", client_id, intent)
            return {"status": "error", "message": "Integration temporarily unavailable. Will retry automatically."}
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        except MaxRetriesExceededError:
            dead_letter_handler.apply_async( # type: ignore
                args=[self.name, list(self.request.args), self.request.kwargs or {}, str(exc)],
                queue="dead_letter",
            )
            return {"status": "error", "message": "Could not complete after retries."}


def _notify_channel(client_id, task_id, result, sender="", channel="telegram",
                    file_bytes=b"", mime_type=""):
    """Execute notify channel."""
    try:
        reply = result.get("message") or (
            "I can help with invoices, payments, expenses, and admin tasks."
            if result.get("status") == "out_of_scope"
            else "Processed."
        )

        resolved_sender = (
            sender
            or _redis.get(f"task:sender:{task_id}")
            or _redis.get(f"task:sender:twilio_whatsapp:{task_id}")
            or _redis.get(f"task:sender:whatsapp:{task_id}")
            or _redis.get(f"twilio_whatsapp:last_sender:{client_id}")
            or _redis.get(f"telegram:last_sender:{client_id}")
        )
        resolved_channel = channel or _redis.get(f"task:channel:{task_id}") or "telegram"

        if not resolved_sender:
            return

        pdf_bytes: bytes | None = None
        pdf_filename: str = ""
        is_storage_file: bool = False

        result_data = result.get("result", {})
        if isinstance(result_data, dict):
            raw_pdf = result_data.get("pdf")
            if isinstance(raw_pdf, (bytes, bytearray)) and raw_pdf:
                pdf_bytes = bytes(raw_pdf)

            if not pdf_bytes:
                raw_file = result_data.get("file_bytes")
                if isinstance(raw_file, (bytes, bytearray)) and raw_file:
                    pdf_bytes = bytes(raw_file)
                    pdf_filename = result_data.get("filename", "document")
                    is_storage_file = True

        invoice = result.get("invoice", {}) or {}
        po      = result.get("po", {}) or {}
        inv_num = (
            result.get("po_number")
            or po.get("po_number")
            or invoice.get("invoice_number")
            or ""
        )
        vendor = po.get("vendor") or invoice.get("vendor") or ""

        if is_storage_file:
            import mimetypes
            send_filename = pdf_filename or "document"
            mime_type     = mimetypes.guess_type(send_filename)[0] or "application/octet-stream"
            caption       = f" {send_filename}"
        else:
            send_filename = f"{inv_num or 'invoice'}.pdf"
            mime_type     = "application/pdf"
            caption       = f"{inv_num} — {vendor}".strip(" —")

        if resolved_channel == "telegram":
            from channels.telegram import TelegramChannel
            ch = TelegramChannel(client_id=client_id)
            ch.send(recipient=str(resolved_sender), message=reply)
            if pdf_bytes:
                ch.send_document(
                    recipient=str(resolved_sender),
                    document=pdf_bytes,
                    filename=send_filename,
                    caption=caption,
                )
        elif resolved_channel == "whatsapp":
            from channels.whatsapp import WhatsAppChannel
            ch = WhatsAppChannel(client_id=client_id)
            ch.send(recipient=str(resolved_sender), message=reply)
            if pdf_bytes:
                ch.send_document(
                    recipient=str(resolved_sender),
                    document=pdf_bytes,
                    filename=send_filename,
                    caption=caption,
                )
        elif resolved_channel == "twilio_whatsapp":
            from channels.twilio_whatsapp import TwilioWhatsAppChannel
            ch = TwilioWhatsAppChannel(client_id=client_id)
            ch.send(recipient=str(resolved_sender), message=reply)
            if pdf_bytes:
                ch.send_document(
                    recipient=str(resolved_sender),
                    document=pdf_bytes,
                    filename=send_filename,
                    caption=caption,
                )

        from core.conversation import save_agent_reply, save_task_result
        save_task_result(str(resolved_sender), client_id, task_id, result)
        save_agent_reply(str(resolved_sender), client_id, reply)

        if (
            result.get("action") in ("file_document", "upload_document")
            and result.get("status") == "success"
            and resolved_sender
            and file_bytes
        ):
            from core.conversation import save_file_bytes_context
            result_d = result.get("result", {}) or {}
            save_file_bytes_context(
                sender=str(resolved_sender),
                client_id=client_id,
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=result_d.get("filename", "document"),
            )

        if (pdf_bytes and not is_storage_file and inv_num and inv_num not in ("", "invoice", "Pending sync", "pending")):
            try:
                pdf_key    = f"conv:pdf:{client_id}:{resolved_sender}"
                result_key = f"conv:last_result:{client_id}:{resolved_sender}"
                _redis.setex(pdf_key, 7200, pdf_bytes.hex())
                existing_raw = _redis.get(result_key)
                if existing_raw:
                    existing = json.loads(str(existing_raw))
                    existing["has_pdf"]        = True
                    existing["invoice_number"] = existing.get("invoice_number") or inv_num
                    existing["vendor"]         = existing.get("vendor") or vendor
                    _redis.setex(result_key, 7200, json.dumps(existing))
            except Exception as cache_exc:
                logger.debug("PDF cache extend failed client=%s: %s", client_id, cache_exc)

    except Exception as e:
        logger.error("_notify_channel failed client=%s task=%s: %s", client_id, task_id, e)


@celery_app.task(name="core.tasks.dead_letter_handler", queue="dead_letter")
def dead_letter_handler(task_name, args, kwargs, reason):
    """Execute dead letter handler."""
    client_id = kwargs.get("client_id", "unknown")
    log_action(client_id, task_name, kwargs.get("intent", "unknown"),
               str(args), {"reason": reason}, "dead_letter")
    send_client_telegram_alert(client_id, "A request could not be completed after retries. Our team has been notified.")
    send_telegram_alert(f"[DEAD LETTER] {task_name} | client={client_id} | {reason[:200]}")
    logger.error("Dead letter: task=%s client=%s reason=%s", task_name, client_id, reason)


@celery_app.task(name="core.tasks.drain_audit_fallback", queue="low")
def drain_audit_fallback():
    """Execute drain audit fallback."""
    from security.audit import drain_fallback
    return {"drained": drain_fallback()}


@celery_app.task(name="core.tasks.beat_heartbeat", queue="low")
def beat_heartbeat():
    """Execute beat heartbeat."""
    _redis.set("health:beat:last_run", time.time())
    return {"status": "ok"}


@celery_app.task(name="core.tasks.celery_health_alert", queue="low")
def celery_health_alert():
    """Execute celery health alert."""
    inspector = celery_app.control.inspect(timeout=3)
    active    = inspector.active()
    if active is None:
        send_telegram_alert("Celery workers DOWN — no workers responding")
    return {"status": "ok", "workers": len(active) if active else 0}


@celery_app.task(name="core.tasks.invoice_reminder_sweep", queue="low")
def invoice_reminder_sweep():
    """Execute invoice reminder sweep."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id,client_id,invoice_number,vendor,amount,currency,
                       due_date,reminder_count,raw_message
                FROM invoices
                WHERE status NOT IN ('paid','cancelled') AND due_date IS NOT NULL
                  AND due_date < CURRENT_DATE AND reminder_count < 4
                  AND (reminder_sent_at IS NULL
                    OR (reminder_count=1 AND reminder_sent_at<NOW()-INTERVAL '7 days')
                    OR (reminder_count=2 AND reminder_sent_at<NOW()-INTERVAL '14 days')
                    OR (reminder_count=3 AND reminder_sent_at<NOW()-INTERVAL '21 days'))
                LIMIT 500
            """)
            rows = cur.fetchall()
            cur.close()
        swept = 0
        for inv_id, client_id, inv_num, vendor, amount, currency, due_date, count, raw in rows:
            try:
                raw_data  = json.loads(raw) if raw else {}
                recipient = raw_data.get("recipient_email")
                if not recipient:
                    continue
                agent = InvoiceAgent(client_id=client_id)
                result = agent.execute_tool("send_reminder", {
                    "invoice_number":  inv_num,
                    "vendor":          vendor,
                    "recipient_email": recipient,
                    "_sender":    "",
                    "_channel":   "email",
                    "_client_id": client_id,
                    "_task_id":   "",
                })

                if not result.get("error"):
                    swept += 1
                    log_action(client_id, "a01_invoice", "reminder_sent", inv_num,
                               {"recipient": recipient}, "success")
                else:
                    log_action(client_id, "a01_invoice", "reminder_failed", inv_num,
                               {"error": result["error"]}, "error")

            except Exception as e:
                log_action(client_id, "a01_invoice", "reminder_failed", inv_num, {"error": str(e)}, "error")
        return {"swept": swept, "total": len(rows)}
    except Exception as e:
        logger.error("invoice_reminder_sweep failed: %s", e)
        return {"error": str(e)}


@celery_app.task(name="core.tasks.document_expiry_sweep", queue="low")
def document_expiry_sweep():
    """
    For each expiring document, run the AdminAgent tool loop to send an alert.
    """
    from datetime import date
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id,client_id,doc_type,filename,expiry_date,alert_count FROM documents
                WHERE status!='expired' AND expiry_date IS NOT NULL
                  AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE+INTERVAL '90 days'
                  AND alert_count<3
                  AND (alert_sent_at IS NULL
                    OR (alert_count=1 AND alert_sent_at<NOW()-INTERVAL '30 days')
                    OR (alert_count=2 AND alert_sent_at<NOW()-INTERVAL '60 days'))
                LIMIT 200
            """)
            rows = cur.fetchall()
            cur.close()
        swept = 0
        for doc_id, client_id, doc_type, filename, expiry_date, count in rows:
            try:
                from config.client_config import get_client_config
                config   = get_client_config(client_id)
                approver = config.get("approve_email")
                if not approver:
                    continue
                days_left = (expiry_date - date.today()).days
                agent = AdminAgent(client_id=client_id)
                result    = agent.execute_tool("send_communication", {
                    "recipient_email": approver,
                    "entity_name":     filename,
                    "content": (
                        f"Document expiry alert: '{filename}' ({doc_type}) "
                        f"expires in {days_left} days on {expiry_date}. Please arrange renewal."
                    ),
                    "_sender":    "",
                    "_channel":   "email",
                    "_client_id": client_id,
                    "_task_id":   "",
                })

                if not result.get("error"):
                    with get_conn() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE documents SET alert_count=alert_count+1, alert_sent_at=NOW(),"
                            "status=CASE WHEN expiry_date<CURRENT_DATE THEN 'expired' ELSE status END WHERE id=%s",
                            (doc_id,)
                        )
                        cur.close()
                    swept += 1
                    log_action(client_id, "a03_admin", "expiry_alert_sent", filename,
                               {"days_left": days_left}, "success")
                else:
                    log_action(client_id, "a03_admin", "expiry_alert_failed", filename,
                               {"error": result["error"]}, "error")

            except Exception as e:
                log_action(client_id, "a03_admin", "expiry_alert_failed", filename, {"error": str(e)}, "error")
        return {"swept": swept}
    except Exception as e:
        logger.error("document_expiry_sweep failed: %s", e)
        return {"error": str(e)}


@celery_app.task(name="core.tasks.payment_reminder_sweep", queue="low")
def payment_reminder_sweep():
    """
    For each overdue invoice, run the PaymentAgent tool loop to send a payment reminder.
    """
    from datetime import date
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id,client_id,invoice_number,vendor,amount,currency,due_date,reminder_count
                FROM invoices
                WHERE status NOT IN ('paid','cancelled') AND due_date<CURRENT_DATE AND reminder_count<4
                  AND (reminder_sent_at IS NULL
                    OR (reminder_count=1 AND reminder_sent_at<NOW()-INTERVAL '7 days')
                    OR (reminder_count=2 AND reminder_sent_at<NOW()-INTERVAL '14 days')
                    OR (reminder_count=3 AND reminder_sent_at<NOW()-INTERVAL '21 days'))
                LIMIT 500
            """)
            rows = cur.fetchall()
            cur.close()
        swept = 0
        for inv_id, client_id, inv_num, vendor, amount, currency, due_date, count in rows:
            try:
                from config.client_config import get_client_config
                config      = get_client_config(client_id)
                approver    = config.get("approve_email")
                if not approver:
                    continue

                agent  = PaymentAgent(client_id=client_id)
                result = agent.execute_tool("send_payment_reminder", {
                    "payer":       vendor,
                    "payer_email": approver,
                    "invoice_ref": inv_num,
                    "_sender":    "",
                    "_channel":   "email",
                    "_client_id": client_id,
                    "_task_id":   "",
                })

                if not result.get("error"):
                    swept += 1
                    log_action(client_id, "a04_payment", "reminder_sent", inv_num,
                               {"days_overdue": (date.today() - due_date).days}, "success")
                else:
                    log_action(client_id, "a04_payment", "reminder_failed", inv_num,
                               {"error": result["error"]}, "error")

            except Exception as e:
                log_action(client_id, "a04_payment", "reminder_failed", inv_num, {"error": str(e)}, "error")
        return {"swept": swept}
    except Exception as e:
        logger.error("payment_reminder_sweep failed: %s", e)
        return {"error": str(e)}

@celery_app.task(name="core.tasks.autonomous_overdue_invoice_sweep", queue="low")
def autonomous_overdue_invoice_sweep():
    """
    Runs InvoiceAgent in autonomous mode across all clients.
    """
    from config.client_config import get_all_client_ids
    processed = 0
    for client_id in get_all_client_ids():
        try:
            agent  = InvoiceAgent(client_id=client_id)
            result = agent.run_loop({
                "message": "Check all overdue invoices and send payment reminders to each one",
                "sender":  "",
                "channel": "autonomous",
                "domain":  "invoice",
            })
            if result.get("status") == "success":
                processed += 1
                logger.info("autonomous_overdue_invoice_sweep: client=%s loops=%d",
                            client_id, result.get("loops", 0))
        except Exception as exc:
            logger.warning("autonomous_overdue_invoice_sweep failed client=%s: %s", client_id, exc)

    return {"clients_processed": processed}


@celery_app.task(name="core.tasks.autonomous_expense_approval_sweep", queue="low")
def autonomous_expense_approval_sweep():
    """
    Runs ExpenseAgent in autonomous mode.
    Agent lists pending expenses and auto-approves those within threshold.
    """
    from config.client_config import get_all_client_ids
    processed = 0
    for client_id in get_all_client_ids():
        try:
            agent  = ExpenseAgent(client_id=client_id)
            result = agent.run_loop({
                "message": "List all pending expenses and approve those that are ready for approval",
                "sender":  "",
                "channel": "autonomous",
                "domain":  "expense",
            })
            if result.get("status") == "success":
                processed += 1
        except Exception as exc:
            logger.warning("autonomous_expense_approval_sweep failed client=%s: %s", client_id, exc)

    return {"clients_processed": processed}


@celery_app.task(name="core.tasks.autonomous_payment_reconcile_sweep", queue="low")
def autonomous_payment_reconcile_sweep():
    """
    Runs PaymentAgent in autonomous mode.
    Agent checks for unreconciled payments and attempts to match them to invoices.
    """
    from config.client_config import get_all_client_ids
    processed = 0
    for client_id in get_all_client_ids():
        try:
            agent  = PaymentAgent(client_id=client_id)
            result = agent.run_loop({
                "message": "Check for any unmatched payments and reconcile them against open invoices",
                "sender":  "",
                "channel": "autonomous",
                "domain":  "payment",
            })
            if result.get("status") == "success":
                processed += 1
        except Exception as exc:
            logger.warning("autonomous_payment_reconcile_sweep failed client=%s: %s", client_id, exc)

    return {"clients_processed": processed}


@celery_app.task(bind=True, max_retries=5, queue="low", name="core.tasks.retry_accounting_post")
def retry_accounting_post(self, client_id, data, sender="", channel=""):
    """Execute retry accounting post."""
    from integrations.accounting_factory import get_system_from_config
    provider = _get_accounting_provider(client_id)
    if provider and _is_breaker_open(provider, client_id):
        raise self.retry(exc=Exception(f"CB open {provider}:{client_id}"), countdown=300)
    try:
        result  = get_system_from_config(client_id).create_invoice(data)
        inv_num = result.get("InvoiceNumber") or result.get("DocNumber") if result else None
        ext_id  = result.get("InvoiceID")     or result.get("Id")        if result else None

        if ext_id and data.get("idempotency_key"):
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE invoices "
                    "SET external_id=%s, invoice_number=COALESCE(NULLIF(invoice_number,''), %s) "
                    "WHERE idempotency_key=%s",
                    (ext_id, inv_num, data["idempotency_key"]),
                )
                cur.close()

        resolved_sender  = sender  or _redis.get(f"telegram:last_sender:{client_id}")
        resolved_channel = channel or _redis.get(f"task:channel:{client_id}") or "telegram"

        if resolved_sender and inv_num:
            vendor   = data.get("vendor", "")
            currency = data.get("currency", "USD")
            amount   = data.get("amount", "")

            pdf_bytes: bytes | None = None
            if ext_id:
                try:
                    pdf_bytes = get_system_from_config(client_id).get_invoice_pdf(ext_id)
                except Exception as pdf_exc:
                    logger.warning("Post-sync PDF fetch failed client=%s: %s", client_id, pdf_exc)

            msg = (
                f"Invoice {inv_num} for {vendor} ({currency} {amount}) has been synced successfully."
                + (" PDF attached." if pdf_bytes else "")
            )

            if resolved_channel == "telegram":
                from channels.telegram import TelegramChannel
                ch = TelegramChannel(client_id=client_id)
                ch.send(recipient=str(resolved_sender), message=msg)
                if pdf_bytes:
                    ch.send_document(recipient=str(resolved_sender), document=pdf_bytes,
                                     filename=f"{inv_num}.pdf", caption=f"{inv_num} — {vendor}".strip(" —"))
            elif resolved_channel == "whatsapp":
                from channels.whatsapp import WhatsAppChannel
                ch = WhatsAppChannel(client_id=client_id)
                ch.send(recipient=str(resolved_sender), message=msg)
                if pdf_bytes:
                    ch.send_document(recipient=str(resolved_sender), document=pdf_bytes,
                                     filename=f"{inv_num}.pdf", caption=f"{inv_num} — {vendor}".strip(" —"))

        log_action(client_id, "a01_invoice", "accounting_retry", "", result or {}, "success")
        return result

    except Exception as exc:
        if "Business Validation Error" in str(exc) or "QuickBooksValidationError" in type(exc).__name__:
            logger.error("Non-retryable QB validation error — dropping retry client=%s: %s", client_id, exc)
            return {"error": str(exc), "dropped": True}
        raise self.retry(exc=exc, countdown=300 if _is_cb_error(exc) else 2 ** self.request.retries * 60)


@celery_app.task(bind=True, max_retries=5, queue="low", name="core.tasks.retry_expense_accounting_post")
def retry_expense_accounting_post(self, client_id, data):
    """Execute retry expense accounting post."""
    from integrations.accounting_factory import get_system_from_config
    provider = _get_accounting_provider(client_id)
    if provider and _is_breaker_open(provider, client_id):
        raise self.retry(exc=Exception(f"CB open {provider}:{client_id}"), countdown=300)
    try:
        result = get_system_from_config(client_id).post_expense(data)
        ext_id = (
            result.get("InvoiceID") or result.get("ReceiptID") or result.get("Id")
            or (result.get("Purchase") or {}).get("Id")
        ) if result else None
        if ext_id and data.get("idempotency_key"):
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE expenses SET external_id=%s WHERE idempotency_key=%s", (ext_id, data["idempotency_key"]))
                cur.close()
        log_action(client_id, "a02_expense", "accounting_retry", "", result or {}, "success")
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=300 if _is_cb_error(exc) else 2 ** self.request.retries * 60)


@celery_app.task(name="core.tasks.refresh_oauth_tokens", queue="low")
def refresh_oauth_tokens():
    """Execute refresh oauth tokens."""
    OAUTH_SERVICES = ["xero", "quickbooks", "google", "outlook", "paypal"]
    THRESHOLD = 1800
    from integrations.resilience import CircuitBreaker
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT client_id,provider FROM client_integrations "
                "WHERE connected=TRUE AND provider=ANY(%s)",
                (OAUTH_SERVICES,)
            )
            rows = cur.fetchall()
            cur.close()
    except Exception as e:
        logger.error("refresh_oauth_tokens query failed: %s", e)
        return {"error": str(e)}

    refreshed = skipped = failed = 0
    for client_id, provider in rows:
        service = f"{provider}:{client_id}"
        try:
            stored = get_stored_token(service)
            if not stored:
                _mark_disconnected(client_id, provider)
                skipped += 1
                continue
            rt = stored.get("refresh_token", "")
            if not rt:
                skipped += 1
                continue
            rt_exp    = float(stored.get("refresh_token_expires_at", 0))
            days_left = (rt_exp - time.time()) / 86400
            if days_left <= 0:
                handle_dead_token(provider, client_id)
                failed += 1
                continue
            if days_left <= 7:
                warned_key = f"reconnect:warned:{service}"
                if not _redis.get(warned_key):
                    send_client_telegram_alert(
                        client_id,
                        f"Your {provider.title()} connection expires in {int(days_left)} day(s). "
                        f"Reconnect here: {settings.frontend_url}/client-dashboard/integration",
                    )
                    _redis.setex(warned_key, 86400 * 3, "1")
            exp = float(stored.get("expires_at", 0))
            if exp - time.time() > THRESHOLD:
                skipped += 1
                continue
            do_refresh(provider, rt, client_id=client_id)
            try:
                breaker = CircuitBreaker(service)
                if breaker.status()["state"] != "closed":
                    breaker.reset()
            except Exception as cb_exc:
                logger.debug("Circuit breaker reset skipped: %s", cb_exc)
            refreshed += 1
        except Exception as e:
            failed += 1
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (400, 401):
                handle_dead_token(provider, client_id)
            log_action(client_id, "token_manager", "refresh_failed", provider, {"error": str(e)}, "error")

    return {"refreshed": refreshed, "skipped": skipped, "failed": failed}


@celery_app.task(name="core.tasks.webhook_health_check", queue="low")
def webhook_health_check():
    """Execute webhook health check."""
    from config.channel_registry import register_channel_token
    expected_tg  = f"{settings.backend_url}/webhooks/telegram"
    reregistered = 0

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT ct.channel, ct.token, ct.client_id
                FROM channel_tokens ct
                JOIN client_integrations ci
                ON ci.client_id = ct.client_id
                AND ci.provider = ct.channel
                WHERE ci.connected = TRUE
            """)
            rows = cur.fetchall()
            cur.close()
    except Exception as e:
        return {"error": str(e)}

    for channel, token, client_id in rows:
        try:
            stored    = get_stored_token(f"{channel}:{client_id}")
            raw_token = stored.get("access_token") if stored else None
            if not raw_token:
                continue

            if channel == "telegram":
                r           = httpx.get(f"https://api.telegram.org/bot{raw_token}/getWebhookInfo", timeout=10)
                current_url = r.json().get("result", {}).get("url", "")
                if current_url != expected_tg:
                    httpx.post(f"https://api.telegram.org/bot{raw_token}/setWebhook",
                               data={"url": expected_tg, "secret_token": client_id}, timeout=10)
                    register_channel_token("telegram", client_id, client_id, expected_tg, True)
                    reregistered += 1

            elif channel == "whatsapp":
                sandbox     = settings.env == "development"
                base        = "https://waba-sandbox.360dialog.io" if sandbox else "https://waba.360dialog.io"
                expected_wa = f"{settings.backend_url}/webhooks/whatsapp/{client_id}"
                check       = httpx.get(f"{base}/v1/configs/webhook", headers={"D360-API-KEY": raw_token}, timeout=10)
                current_url = check.json().get("url", "")
                if current_url != expected_wa:
                    fix = httpx.post(f"{base}/v1/configs/webhook",
                                     headers={"D360-API-KEY": raw_token, "Content-Type": "application/json"},
                                     json={"url": expected_wa}, timeout=10)
                    if fix.status_code == 200:
                        register_channel_token("whatsapp", raw_token, client_id, expected_wa, True)
                        reregistered += 1

        except Exception as e:
            log_action(client_id, "webhook_health", f"reregister_{channel}", client_id, {"error": str(e)}, "error")

    return {"checked": len(rows), "reregistered": reregistered}


@celery_app.task(name="core.tasks.metrics_report", queue="low")
def metrics_report():
    """Execute metrics report."""
    from core.intelligence_loop import get_agent_health
    health       = get_agent_health(window_days=7)
    total_alerts = sum(len(v.get("alerts", [])) for v in health.values())
    return {"agents": len(health), "alerts": total_alerts}


@celery_app.task(name="core.tasks.classifier_feedback", queue="low")
def classifier_feedback():
    """Execute classifier feedback."""
    from core.intelligence_loop import collect_classifier_feedback
    stored = collect_classifier_feedback(limit=100)
    return {"stored": stored}


@celery_app.task(name="core.tasks.proactive_insights", queue="low")
def proactive_insights():
    """Execute proactive insights."""
    from config.client_config import get_all_client_ids
    from core.intelligence_loop import run_proactive_insights
    sent = 0
    for client_id in get_all_client_ids():
        try:
            for insight in run_proactive_insights(client_id):
                send_client_telegram_alert(client_id, insight)
                sent += 1
        except Exception as exc:
            logger.warning("proactive_insights failed for %s: %s", client_id, exc)
    return {"insights_sent": sent}


@celery_app.task(name="core.tasks.summarize_all_memories", queue="low")
def summarize_all_memories():
    """Execute summarize all memories."""
    from core.intelligence_loop import summarize_agent_memory
    from config.client_config import get_all_client_ids
    ran    = 0
    agents = list(set(__import__("core.orchestrator", fromlist=["INTENT_TO_AGENT"]).INTENT_TO_AGENT.values()))
    for client_id in get_all_client_ids():
        for agent_name in agents:
            try:
                if summarize_agent_memory(client_id, agent_name):
                    ran += 1
            except Exception as exc:
                logger.warning("summarize_agent_memory failed %s/%s: %s", client_id, agent_name, exc)
    return {"summarized": ran}


@celery_app.task(name="core.tasks.tune_confidence_thresholds", queue="low")
def tune_confidence_thresholds():
    """Execute tune confidence thresholds."""
    from core.intelligence_loop import tune_client_confidence
    changes = tune_client_confidence()
    return {"clients_tuned": len(changes), "changes": changes}