"""Contain intelligence loop backend logic."""
from __future__ import annotations
import json
import logging

from typing import Optional

from config.db_pool import get_conn
from config.settings import settings
from core.alerting import send_telegram_alert

logger= logging.getLogger(__name__)

# Constant for escalation rate alert.
ESCALATION_RATE_ALERT = 20.0
# Constant for error rate alert.
ERROR_RATE_ALERT = 10.0
# Constant for confidence drift alert.
CONFIDENCE_DRIFT_ALERT = 0.08

def record_outcome(
    client_id:str,
    agent_name:str,
    intent:str,
    action:Optional[str],
    status:str,
    confidence:float,
    duration_ms:int=0,
) ->None:
    """Execute record outcome."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_metrics
                    (client_id, agent_name, intent, action,
                     status, confidence, duration_ms, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (client_id, agent_name, intent, action,
                 status, confidence, duration_ms),
            )
            cur.close()
    except Exception as exc:
        logger.warning("record_outcome failed (non-fatal): %s", exc)

def get_agent_health(window_days: int = 7) -> dict[str, dict]:
    """Return agent health."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    agent_name,
                    COUNT(*)                                                     AS total,
                    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'escalate')
                          / NULLIF(COUNT(*), 0), 1)                             AS escalation_rate,
                    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'error')
                          / NULLIF(COUNT(*), 0), 1)                             AS error_rate,
                    ROUND(AVG(confidence)::NUMERIC, 3)                          AS avg_confidence,
                    ROUND(AVG(confidence) FILTER (
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                    )::NUMERIC, 3)                                              AS confidence_24h,
                    ROUND(AVG(duration_ms) FILTER (
                        WHERE status = 'success'
                    )::NUMERIC, 0)                                              AS avg_duration_ms
                FROM agent_metrics
                WHERE created_at > NOW() - (%s || ' days')::INTERVAL
                GROUP BY agent_name
                ORDER BY agent_name
                """,
                (str(window_days),),
            )
            rows = cur.fetchall()
            cur.close()
    except Exception as exc:
        logger.error("get_agent_health query failed: %s", exc)
        return {}
 
    health: dict[str, dict] = {}
 
    for row in rows:
        (agent_name, total, esc_rate, err_rate,
         avg_conf, conf_24h, avg_dur) = row
 
        esc_f = float(esc_rate  or 0)
        err_f = float(err_rate  or 0)
        avg_c = float(avg_conf  or 0)
        c_24h = float(conf_24h  or 0)
        alerts= []
 
        if esc_f > ESCALATION_RATE_ALERT:
            alerts.append("high_escalation_rate")
            send_telegram_alert(
                f"[DEGRADATION] {agent_name}: escalation rate {esc_f:.1f}% "
                f"over last {window_days}d - prompt may need review"
            )
 
        if err_f > ERROR_RATE_ALERT:
            alerts.append("high_error_rate")
            send_telegram_alert(
                f"[DEGRADATION] {agent_name}: error rate {err_f:.1f}% "
                f"over last {window_days}d - check integrations"
            )
 
        if avg_c > 0 and c_24h > 0:
            drift = avg_c - c_24h
            if drift > CONFIDENCE_DRIFT_ALERT:
                alerts.append("confidence_drift")
                send_telegram_alert(
                    f"[DRIFT] {agent_name}: confidence dropped "
                    f"{drift:.3f} in last 24h (was {avg_c:.3f}, now {c_24h:.3f})"
                )
 
        health[agent_name] = {
            "total": int(total or 0),
            "escalation_rate": esc_f,
            "error_rate": err_f,
            "avg_confidence": avg_c,
            "confidence_24h": c_24h,
            "avg_duration_ms": int(avg_dur or 0),
            "alerts": alerts,
        }
 
        logger.info(
            "Agent health [%s]: total=%d esc=%.1f%% err=%.1f%% "
            "conf=%.3f conf_24h=%.3f alerts=%s",
            agent_name, int(total or 0), esc_f, err_f,
            avg_c, c_24h, alerts,
        )
 
    return health


def collect_classifier_feedback(limit: int = 100) -> int:
    """Execute collect classifier feedback."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT am.intent, am.confidence, al.raw_message
                FROM agent_metrics am
                JOIN audit_log al
                  ON al.client_id = am.client_id
                WHERE am.status IN ('escalate', 'error')
                  AND am.confidence BETWEEN 0.5 AND 0.75
                  AND am.created_at > NOW() - INTERVAL '7 days'
                  AND al.raw_message IS NOT NULL
                  AND LENGTH(al.raw_message) > 10
                ORDER BY am.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
    except Exception as exc:
        logger.error("collect_classifier_feedback query failed: %s", exc)
        return 0
 
    if not rows:
        return 0
 
    from memory.rag import store_knowledge
    stored = 0
 
    for intent, confidence, message in rows:
        if not message:
            continue
        content = (
            f"example_intent:{intent} | "
            f"confidence:{confidence:.2f} | "
            f"message:{message[:200]}"
        )
        if store_knowledge(
            client_id="__system__",
            category="classifier_examples",
            content=content,
        ):
            stored += 1
 
    logger.info("Classifier feedback: stored %d/%d examples", stored, len(rows))
    return stored

def get_classifier_examples(query: str, top_k: int = 5) -> str:
    """Return classifier examples."""
    from memory.rag import retrieve_knowledge
    return retrieve_knowledge(
        client_id="__system__",
        query=query,
        category="classifier_examples",
        top_k=top_k,
        min_similarity=0.4,
    )

def run_proactive_insights(client_id: str) -> list[str]:
    """Run proactive insights."""
    insights: list[str] = []
    insights.extend(_check_cash_flow_risk(client_id))
    insights.extend(_check_expense_spike(client_id))
    insights.extend(_check_slow_payers(client_id))
    return insights
 
def _check_cash_flow_risk(client_id: str) -> list[str]:
    """Check cash flow risk."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*), SUM(amount), currency
                FROM invoices
                WHERE client_id = %s
                  AND status = 'overdue'
                  AND due_date < CURRENT_DATE - INTERVAL '30 days'
                GROUP BY currency
                """,
                (client_id,),
            )
            rows = cur.fetchall()
            cur.close()
 
        messages = []
        for count, total, currency in rows:
            if count and count >= 3:
                messages.append(
                    f"Cash flow alert: {count} invoices overdue 30+ days "
                    f"totalling {currency} {float(total or 0):.2f}. "
                    f"Want me to send escalation reminders?"
                )
        return messages
    except Exception as exc:
        logger.warning("_check_cash_flow_risk failed: %s", exc)
        return []


def _check_expense_spike(client_id: str) -> list[str]:
    """Check expense spike."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    category,
                    SUM(amount) FILTER (WHERE created_at > NOW() - INTERVAL '30 days')  AS this_month,
                    SUM(amount) FILTER (WHERE created_at BETWEEN
                        NOW() - INTERVAL '60 days' AND NOW() - INTERVAL '30 days')      AS last_month
                FROM expenses
                WHERE client_id = %s
                GROUP BY category
                HAVING SUM(amount) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') IS NOT NULL
                """,
                (client_id,),
            )
            rows = cur.fetchall()
            cur.close()
 
        messages = []
        for category, this_m, last_m in rows:
            if last_m and this_m and float(last_m) > 0:
                pct = ((float(this_m) - float(last_m)) / float(last_m)) * 100
                if pct > 40:
                    messages.append(
                        f"Spend alert: {category} costs up {pct:.0f}% vs last month. "
                        f"Want a breakdown?"
                    )
        return messages
    except Exception as exc:
        logger.warning("_check_expense_spike failed: %s", exc)
        return []

def _check_slow_payers(client_id: str) -> list[str]:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT vendor, COUNT(*) AS late_count
                FROM invoices
                WHERE client_id = %s
                  AND status IN ('overdue', 'paid')
                  AND due_date IS NOT NULL
                  AND (
                      status = 'overdue'
                      OR (status = 'paid' AND created_at > due_date + INTERVAL '7 days')
                  )
                GROUP BY vendor
                HAVING COUNT(*) >= 3
                ORDER BY late_count DESC
                LIMIT 3
                """,
                (client_id,),
            )
            rows = cur.fetchall()
            cur.close()

        messages = []
        for vendor, count in rows:
            messages.append(
                f"Payment pattern: {vendor} has been late {count} times. "
                f"Want me to add late-payment terms to future invoices?"
            )
        return messages
    except Exception as exc:
        logger.warning("_check_slow_payers failed: %s", exc)
        return []

def summarize_agent_memory(
    client_id: str,
    agent_name: str,
    threshold: int = 1000,
    compress_n: int = 200,
) -> bool:
    """Execute summarize agent memory."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE client_id=%s AND agent_name=%s",
                (client_id, agent_name),
            )
            count = cur.fetchone()[0]
            cur.close()
 
        if count <= threshold:
            return False
 
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, content FROM agent_memory
                WHERE client_id=%s AND agent_name=%s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (client_id, agent_name, compress_n),
            )
            rows = cur.fetchall()
            cur.close()
 
        if not rows:
            return False
 
        ids      = [r[0] for r in rows]
        contents = [r[1] for r in rows]
 
        summary = _compress_memories(contents, agent_name)
        if not summary:
            return False
 
        from memory.agent_memory import save_memory
        save_memory(client_id, agent_name, f"[SUMMARY] {summary}")
 
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM agent_memory WHERE id = ANY(%s)", (ids,))
            cur.close()
 
        logger.info(
            "Memory summarized: client=%s agent=%s compressed=%d",
            client_id, agent_name, len(ids),
        )
        return True
 
    except Exception as exc:
        logger.error(
            "summarize_agent_memory failed (client=%s agent=%s): %s",
            client_id, agent_name, exc,
        )
        return False


def _compress_memories(contents: list[str], agent_name: str) -> str:
    """Execute compress memories."""
    from agents.base_agent import _get_client
    joined = "\n".join(f"- {c}" for c in contents[:100])
    prompt = (
        f"The following are chronological action records for agent '{agent_name}'.\n"
        f"Compress them into a concise factual summary (max 300 words).\n"
        f"Preserve: entity names, amounts, dates, outcomes. Drop: duplicates, noise.\n\n"
        f"{joined}"
    )
    try:
        res = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in res.content:
            if block.type == "text":
                return block.text.strip()
        return ""
    except Exception as exc:
        logger.error("_compress_memories LLM call failed: %s", exc)
        return ""


def tune_client_confidence(window_days: int = 14) -> dict[str, dict]:
    """Execute tune client confidence."""
    GLOBAL_DEFAULT = 0.70
    MIN_THRESHOLD = 0.50
    HIGH_ESC_RATE = 25.0
    LOW_ESC_RATE = 5.0
    TUNE_STEP = 0.05
    MIN_SAMPLES = 20
 
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    client_id,
                    intent,
                    COUNT(*) AS total,
                    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'escalate')
                          / NULLIF(COUNT(*), 0), 1) AS escalation_rate
                FROM agent_metrics
                WHERE created_at > NOW() - (%s || ' days')::INTERVAL
                GROUP BY client_id, intent
                HAVING COUNT(*) >= %s
                """,
                (str(window_days), MIN_SAMPLES),
            )
            rows = cur.fetchall()
            cur.close()
    except Exception as exc:
        logger.error("tune_client_confidence query failed: %s", exc)
        return {}
 
    import redis as _r
    _rd     = _r.from_url(settings.redis_url, decode_responses=True)
    changes: dict[str, dict] = {}
 
    for client_id, intent, total, esc_rate in rows:
        esc_f = float(esc_rate or 0)
        key = f"conf_threshold:{client_id}:{intent}"
        current = float(_rd.get(key) or GLOBAL_DEFAULT) # type: ignore
 
        if esc_f > HIGH_ESC_RATE and current > MIN_THRESHOLD:
            new_thresh = max(current - TUNE_STEP, MIN_THRESHOLD)
            _rd.set(key, str(new_thresh))
            _rd.expire(key, 86400 * 30)
            changes.setdefault(client_id, {})[intent] = new_thresh
            logger.info(
                "Confidence tuned DOWN: client=%s intent=%s %.2f→%.2f (esc=%.1f%%)",
                client_id, intent, current, new_thresh, esc_f,
            )
 
        elif esc_f < LOW_ESC_RATE and current < GLOBAL_DEFAULT:
            new_thresh = min(current + TUNE_STEP, GLOBAL_DEFAULT)
            _rd.set(key, str(new_thresh))
            _rd.expire(key, 86400 * 30)
            changes.setdefault(client_id, {})[intent] = new_thresh
            logger.info(
                "Confidence tuned UP: client=%s intent=%s %.2f→%.2f (esc=%.1f%%)",
                client_id, intent, current, new_thresh, esc_f,
            )
 
    return changes

def get_client_confidence(client_id: str, intent: str) -> float:

    """Return client confidence."""
    import redis as _r
    try:
        _rd = _r.from_url(settings.redis_url, decode_responses=True)
        val = _rd.get(f"conf_threshold:{client_id}:{intent}")
        return float(val) if val else 0.70 # type: ignore
    except Exception:
        return 0.70
 
def record_entity_interaction(
    client_id: str,
    entity_name: str,
    agent_name: str,
    domain: str,
    amount: float = 0.0,
    currency: str = "USD",
    late_days: int = 0,
) -> None:
    """Execute record entity interaction."""
    from memory.entity_graph import record_entity_interaction as _record
    _record(
        client_id=client_id,
        entity_name=entity_name,
        agent_name=agent_name,
        domain=domain,
        amount=amount,
        currency=currency,
        late_days=late_days,
    )

_PERSONA_TTL = 86400 * 90
_PERSONA_KEY = "client:persona:{client_id}"


def enrich_from_onboarding(client_id: str) -> bool:
    """Execute enrich from onboarding."""
    try:
        from config.client_config import get_client_config
        config = get_client_config(client_id)
    except Exception as exc:
        logger.warning("enrich_from_onboarding — no config for client=%s: %s", client_id, exc)
        return False

    enrichment = _analyse_with_llm(client_id, config)
    if not enrichment:
        logger.warning("enrich_from_onboarding — LLM analysis returned empty client=%s", client_id)
        return False

    _write_persona(client_id, enrichment.get("persona", {}))
    _apply_confidence_baselines(client_id, enrichment.get("confidence_baselines", {}))
    _apply_entity_seeds(client_id, enrichment.get("entity_seeds", []))

    logger.info(
        "enrich_from_onboarding complete client=%s industry=%s seeds=%d",
        client_id,
        enrichment.get("persona", {}).get("industry", "unknown"),
        len(enrichment.get("entity_seeds", [])),
    )
    return True


def get_client_persona(client_id: str) -> dict:
    """Return client persona."""
    import redis as _r
    try:
        _rd = _r.from_url(settings.redis_url, decode_responses=True)
        raw = _rd.get(_PERSONA_KEY.format(client_id=client_id))
        return json.loads(raw) if raw else {}  # type: ignore[arg-type]
    except Exception:
        return {}


def format_persona_for_prompt(persona: dict) -> str:
    """Execute format persona for prompt."""
    if not persona:
        return ""
    parts: list[str] = []
    if persona.get("industry"):
        parts.append(persona["industry"])
    if persona.get("headcount"):
        parts.append(f"{persona['headcount']} staff")
    systems = [s for s in persona.get("key_systems", []) if s]
    if systems:
        parts.append(" + ".join(systems[:3]))
    if persona.get("primary_compliance"):
        parts.append(f"{persona['primary_compliance']} compliance")
    return ("Client context: " + ", ".join(parts) + ".") if parts else ""


def _analyse_with_llm(client_id: str, config: dict) -> dict:
    """Execute analyse with llm."""
    config_summary = json.dumps({
        k: v for k, v in config.items()
        if k in (
            "industry", "region", "headcount", "revenue",
            "accounting_system", "erp_system", "crm_system",
            "hris_system", "document_store", "payment_system",
            "integrations_summary", "compliance", "active_agents",
            "channels", "challenges", "use_cases",
        )
    }, indent=2)

    prompt = f"""You are analysing a business onboarding profile to configure an AI financial operations system.

Onboarding config:
{config_summary}

Return a JSON object with exactly these fields:

{{
  "persona": {{
    "industry": "one-line industry description e.g. 'Retail & E-commerce'",
    "headcount": "headcount band as string",
    "scale": "startup | small | mid | enterprise",
    "region": "region string",
    "key_systems": ["list", "of", "named", "systems", "they", "use"],
    "primary_compliance": "most important compliance framework or empty string",
    "payment_systems": ["list of payment platforms they use"],
    "accounting_system": "primary accounting system name or empty string"
  }},
  "confidence_baselines": {{
    "invoice": 0.70,
    "expense": 0.70,
    "payment": 0.70,
    "admin": 0.70,
    "po": 0.70
  }},
  "entity_seeds": [
    {{"name": "entity name", "domain": "invoice|expense|payment|admin"}}
  ]
}}

Rules for confidence_baselines (0.50–0.85):
- Set LOWER (0.60–0.65) for intents where this industry commonly uses ambiguous language
- Set HIGHER (0.75–0.82) for intents that are clearly core to their business
- Base this on their industry, systems, and stated use cases — not generic rules

Rules for entity_seeds:
- Include every named system, platform, vendor, or tool mentioned anywhere in the config
- Include their ERP, CRM, HRIS, payment platforms, document stores
- Do NOT invent entities not present in the config
- domain = the most likely agent that would interact with this entity

Reply with valid JSON only. No markdown, no preamble."""

    try:
        from agents.base_agent import _get_client
        import re as _re
        res = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in res.content:
            if block.type == "text":
                text = block.text.strip()
                text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
                text = _re.sub(r"\s*```$", "", text).strip()
                result = json.loads(text)
                if "persona" in result and "confidence_baselines" in result:
                    return result
        logger.error("_analyse_with_llm returned unexpected structure client=%s", client_id)
        return {}
    except Exception as exc:
        logger.error("_analyse_with_llm failed client=%s: %s", client_id, exc)
        return {}


def _write_persona(client_id: str, persona: dict) -> None:
    """Execute write persona."""
    if not persona:
        return
    import redis as _r
    try:
        _rd = _r.from_url(settings.redis_url, decode_responses=True)
        key = _PERSONA_KEY.format(client_id=client_id)
        _rd.set(key, json.dumps(persona))
        _rd.expire(key, _PERSONA_TTL)
    except Exception as exc:
        logger.error("_write_persona failed client=%s: %s", client_id, exc)


def _apply_confidence_baselines(client_id: str, baselines: dict) -> None:
    """Execute apply confidence baselines."""
    if not baselines:
        return
    import redis as _r
    try:
        _rd = _r.from_url(settings.redis_url, decode_responses=True)
        for intent, value in baselines.items():
            key = f"conf_threshold:{client_id}:{intent}"
            if not _rd.exists(key):
                threshold = max(0.50, min(0.85, float(value)))
                _rd.set(key, str(threshold))
                _rd.expire(key, 86400 * 30)
        logger.debug("_apply_confidence_baselines client=%s intents=%s",
                     client_id, list(baselines.keys()))
    except Exception as exc:
        logger.error("_apply_confidence_baselines failed client=%s: %s", client_id, exc)


def _apply_entity_seeds(client_id: str, seeds: list) -> None:
    """Execute apply entity seeds."""
    if not seeds:
        return
    try:
        from memory.entity_graph import record_entity_interaction
        seeded = 0
        for seed in seeds:
            name   = (seed.get("name") or "").strip()
            domain = (seed.get("domain") or "invoice").strip()
            if name:
                record_entity_interaction(
                    client_id=client_id,
                    entity_name=name,
                    agent_name="onboarding",
                    domain=domain,
                    amount=0.0,
                )
                seeded += 1
        logger.debug("_apply_entity_seeds client=%s seeded=%d", client_id, seeded)
    except Exception as exc:
        logger.error("_apply_entity_seeds failed client=%s: %s", client_id, exc)