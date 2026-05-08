"""Contain entity graph backend logic."""
from __future__ import annotations
import logging
import math
from datetime import date, datetime
from typing import Optional
import redis
from redis import Redis
from redis.client import Pipeline
from config.settings import settings

logger = logging.getLogger(__name__)
_redis: Redis[str] = redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[assignment]

# Constant for entity time-to-live.
ENTITY_TTL        = 86400 * 730
# Constant for derived risk time-to-live.
DERIVED_RISK_TTL  = 86400 * 7
_KEY_PREFIX       = "entity"
_MAX_ENTITY_LEN   = 80
_RISK_ALPHA_PRIOR = 1.0
_RISK_BETA_PRIOR  = 5.0


def _key(client_id: str, entity_name: str) -> str:
    """Execute key."""
    n = entity_name.strip().lower().replace(" ", "_")[:_MAX_ENTITY_LEN]
    return f"{_KEY_PREFIX}:{client_id}:{n}"


def _days_since(date_str: Optional[str]) -> float:
    """Execute days since."""
    if not date_str:
        return 180.0
    try:
        return float((date.today() - datetime.strptime(date_str, "%Y-%m-%d").date()).days)
    except Exception:
        return 180.0


def _recency_factor(date_str: Optional[str], half_life: float = 90.0) -> float:
    """Execute recency factor."""
    return math.exp(-math.log(2) * _days_since(date_str) / half_life)


def record_entity_interaction(
    client_id: str, entity_name: str, agent_name: str, domain: str,
    amount: float = 0.0, currency: str = "USD", late_days: int = 0,
) -> None:
    """Execute record entity interaction."""
    if not entity_name or not entity_name.strip():
        return
    try:
        key   = _key(client_id, entity_name)
        pipe: Pipeline = _redis.pipeline(transaction=True)
        pipe.hincrbyfloat(key, f"total_{domain}_amt", amount)
        pipe.hincrby(key, f"total_{domain}s", 1)
        pipe.hset(key, mapping={
            "last_seen":     date.today().isoformat(),
            "last_amount":   str(round(amount, 2)),
            "last_currency": currency,
            "last_agent":    agent_name,
        })
        pipe.execute()

        raw: list   = _redis.hmget(key, ["risk_alpha", "risk_beta"])  # type: ignore[assignment]
        alpha = float(raw[0]) if raw[0] else _RISK_ALPHA_PRIOR
        beta  = float(raw[1]) if raw[1] else _RISK_BETA_PRIOR

        if late_days > 0:
            _redis.hincrby(key, "late_payment_count", 1)
            raw_avg: list = _redis.hmget(key, ["avg_days_late", "late_payment_count"])  # type: ignore[assignment]
            avg     = float(raw_avg[0] or 0)
            cnt     = int(raw_avg[1] or 1)
            new_avg = round(((avg * (cnt - 1)) + late_days) / cnt, 1)
            _redis.hset(key, "avg_days_late", str(new_avg))
            alpha += 1.0
        else:
            beta += 1.0

        _redis.hset(key, mapping={"risk_alpha": alpha, "risk_beta": beta})

        existing: str    = _redis.hget(key, "agents_involved") or ""  # type: ignore[assignment]
        agents: set[str] = set(existing.split(",")) if existing else set()
        agents.discard("")
        agents.add(agent_name)
        _redis.hset(key, "agents_involved", ",".join(sorted(agents)))
        _redis.expire(key, ENTITY_TTL)

        if late_days > 0:
            _propagate_risk_signal(client_id, entity_name, agents, alpha, beta)

    except Exception as exc:
        logger.warning("record_entity_interaction failed: %s", exc, exc_info=True)


def _propagate_risk_signal(
    client_id: str, entity_name: str, agents: set, alpha: float, beta: float,
) -> None:
    """Execute propagate risk signal."""
    try:
        p_late = alpha / (alpha + beta)
        if p_late < 0.35:
            return
        cursor  = 0
        pattern = f"entity:{client_id}:*"
        while True:
            cursor, keys = _redis.scan(cursor, match=pattern, count=100)  # type: ignore[misc]
            for other_key in keys:
                if other_key == _key(client_id, entity_name):
                    continue
                other_str: str = _redis.hget(other_key, "agents_involved") or ""  # type: ignore[assignment]
                if set(other_str.split(",")) & agents:
                    other_suffix = other_key.rsplit(":", 1)[-1]
                    dkey         = f"derived_risk:{client_id}:{other_suffix}"
                    existing     = _redis.get(dkey)
                    if not existing or float(existing) < p_late: # type: ignore
                        _redis.setex(dkey, DERIVED_RISK_TTL, str(round(p_late, 3)))
            if cursor == 0:
                break
    except Exception as exc:
        logger.debug("_propagate_risk_signal non-fatal: %s", exc)


def get_entity_profile(client_id: str, entity_name: str) -> Optional[dict]:
    """Return entity profile."""
    try:
        key  = _key(client_id, entity_name)
        data: dict[str, str] = _redis.hgetall(key)  # type: ignore[assignment]
        if not data:
            return None
        domain_totals: dict = {}
        for k, v in data.items():
            if k.startswith("total_") and k.endswith("_amt"):
                domain_totals.setdefault(k[6:-4], {})["amount"] = round(float(v or 0), 2)
            elif k.startswith("total_") and k.endswith("s") and not k.endswith("_amt"):
                domain_totals.setdefault(k[6:-1], {})["count"] = int(v or 0)
        alpha    = float(data.get("risk_alpha") or _RISK_ALPHA_PRIOR)
        beta_val = float(data.get("risk_beta")  or _RISK_BETA_PRIOR)
        p_late   = round(alpha / (alpha + beta_val), 3)
        norm     = entity_name.strip().lower().replace(" ", "_")[:_MAX_ENTITY_LEN]
        derived  = _redis.get(f"derived_risk:{client_id}:{norm}")
        return {
            "entity": entity_name,
            "last_seen": data.get("last_seen"),
            "last_amount": round(float(data.get("last_amount") or 0), 2),
            "last_currency": data.get("last_currency", "USD"),
            "last_agent": data.get("last_agent"),
            "agents_involved": [a for a in (data.get("agents_involved") or "").split(",") if a],
            "late_payment_count": int(data.get("late_payment_count") or 0),
            "avg_days_late": round(float(data.get("avg_days_late") or 0), 1),
            "domains": domain_totals,
            "risk_score": p_late,
            "derived_risk": float(derived) if derived else None, # type: ignore
        }
    except Exception as exc:
        logger.error("get_entity_profile failed: %s", exc, exc_info=True)
        return None


def get_entity_risk_score(client_id: str, entity_name: str) -> float:
    """Return entity risk score."""
    try:
        key = _key(client_id, entity_name)
        raw: list = _redis.hmget(key, ["risk_alpha", "risk_beta"])  # type: ignore[assignment]
        if raw[0] and raw[1]:
            return round(float(raw[0]) / (float(raw[0]) + float(raw[1])), 3)
        norm    = entity_name.strip().lower().replace(" ", "_")[:_MAX_ENTITY_LEN]
        derived = _redis.get(f"derived_risk:{client_id}:{norm}")
        if derived:
            return float(derived) # type: ignore
    except Exception:
        pass
    return round(_RISK_ALPHA_PRIOR / (_RISK_ALPHA_PRIOR + _RISK_BETA_PRIOR), 3)


def format_entity_context(profile: Optional[dict]) -> str:
    """Execute format entity context."""
    if not profile:
        return ""
    recency  = _recency_factor(profile.get("last_seen"))
    is_stale = recency < 0.25
    lines    = [f"Entity: {profile['entity']}" + (" (stale)" if is_stale else "")]
    currency = profile.get("last_currency", "USD")
    for domain, stats in profile.get("domains", {}).items():
        count  = stats.get("count", 0)
        amount = stats.get("amount", 0.0)
        if count or amount:
            effective  = round(amount * recency, 2) if not is_stale else amount
            decay_note = " (recency-weighted)" if not is_stale and recency < 0.9 else ""
            lines.append(f"{domain.title()}: {count} transactions, {currency} {effective:.2f} total{decay_note}")
    late_count = profile.get("late_payment_count", 0)
    risk_score = profile.get("risk_score", 0.0)
    derived    = profile.get("derived_risk")
    if late_count:
        lines.append(f"Late payments: {late_count} times (avg {profile['avg_days_late']} days late)")
    if risk_score > 0.35:
        lines.append(f"Risk signal: {round(risk_score*100)}% late payment probability (Bayesian)")
    if derived and derived > 0.40 and risk_score <= 0.35:
        lines.append(f"Inferred risk: {round(derived*100)}% (shared agent network with high-risk entity)")
    if profile.get("last_seen"):
        lines.append(f"Last activity: {profile['last_seen']}")
    return "\n".join(lines)