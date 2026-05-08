"""Contain agent memory backend logic."""
from __future__ import annotations
import hashlib
import logging
from typing import Optional
from memory.vector_store import get_embedding, search_similar, store_embedding

logger = logging.getLogger(__name__)
_MIN_CROSS_AGENT_SIMILARITY = 0.30
_MIN_ENTITY_SIMILARITY      = 0.25

def save_memory(client_id: str, agent_name: str, content: str) -> bool:
    """Execute save memory."""
    if not content or not content.strip():
        return False
    try:
        embedding = get_embedding(content)
        stored = store_embedding(
            table="agent_memory",
            client_id=client_id,
            agent_name=agent_name,
            content=content,
            embedding=embedding,
        )
        if stored:
            _record_memory_importance(client_id, agent_name, content)
        return stored
    except Exception as exc:
        logger.error("save_memory failed (client=%s agent=%s): %s",
                     client_id, agent_name, exc)
        return False


def _record_memory_importance(client_id: str, agent_name: str, content: str) -> None:
    """Execute record memory importance."""
    try:
        import redis as _r
        from config.settings import settings
        _redis = _r.from_url(settings.redis_url, decode_responses=True)

        words = content.split()
        length_s = min(len(words) / 50.0, 1.0)
        # Entity density
        cap_words = sum(1 for w in words if w and w[0].isupper())
        entity_s  = min(cap_words / max(len(words), 1) * 3, 1.0)
        importance = round(0.6 * length_s + 0.4 * entity_s, 3)

        content_hash = hashlib.md5(content.encode()).hexdigest()
        freq_key = f"emb_freq:agent_memory:{client_id}:{content_hash}"
        seed = max(1, round(importance * 10))
        _redis.set(freq_key, seed, ex=86400 * 365)
    except Exception as exc:
        logger.debug("_record_memory_importance non-fatal: %s", exc)


def recall_memory(
    client_id: str,
    agent_name: str,
    query: str,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> str:
    """Execute recall memory."""
    if not query or not query.strip():
        return ""
    try:
        query_embedding = get_embedding(query)
        results = search_similar(
            table="agent_memory",
            client_id=client_id,
            agent_name=agent_name,
            query_embedding=query_embedding,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        return "\n".join(r["content"] for r in results)
    except Exception as exc:
        logger.error("recall_memory failed (client=%s agent=%s): %s",
                     client_id, agent_name, exc)
        return ""
def recall_cross_agent(
    client_id: str,
    query: str,
    agent_names: Optional[list[str]] = None,
    top_k_per_agent: int = 3,
) -> dict[str, str]:
    """Execute recall cross agent."""
    from core.orchestrator import INTENT_TO_AGENT

    targets = agent_names or list(set(INTENT_TO_AGENT.values()))
    if not targets or not query.strip():
        return {}

    try:
        query_embedding = get_embedding(query)
    except Exception as exc:
        logger.error("recall_cross_agent embedding failed client=%s: %s", client_id, exc)
        return {}

    memories: dict[str, str] = {}

    for agent_name in targets:
        try:
            results = search_similar(
                table="agent_memory",
                client_id=client_id,
                agent_name=agent_name,
                query_embedding=query_embedding,
                top_k=top_k_per_agent,
                min_similarity=_MIN_CROSS_AGENT_SIMILARITY,
            )
            if results:
                memories[agent_name] = "\n".join(r["content"] for r in results)
        except Exception as exc:
            logger.debug("recall_cross_agent agent=%s failed: %s", agent_name, exc)

    return memories


def recall_entity_history(
    client_id: str,
    entity: str,
    top_k: int = 10,
) -> str:
    """Execute recall entity history."""
    if not entity or not entity.strip():
        return ""

    try:
        agent_weights = _get_entity_agent_weights(client_id, entity)
    except Exception as exc:
        logger.debug("Entity pre-filter failed, falling back to cross-agent: %s", exc)
        agent_weights = None

    if not agent_weights:
        cross = recall_cross_agent(
            client_id=client_id,
            query=entity,
            top_k_per_agent=max(top_k // 4, 2),
        )
        if not cross:
            return ""
        parts = [f"[{a}]\n{t}" for a, t in cross.items()]
        return "\n\n".join(parts)

    total_weight = sum(agent_weights.values()) or 1
    try:
        query_embedding = get_embedding(entity)
    except Exception as exc:
        logger.error("recall_entity_history embedding failed client=%s: %s", client_id, exc)
        return ""

    parts: list[str] = []
    for agent_name, weight in sorted(agent_weights.items(),
                                     key=lambda x: x[1], reverse=True):
        agent_slots = max(1, round((weight / total_weight) * top_k))
        try:
            results = search_similar(
                table="agent_memory",
                client_id=client_id,
                agent_name=agent_name,
                query_embedding=query_embedding,
                top_k=agent_slots,
                min_similarity=_MIN_ENTITY_SIMILARITY,
            )
            if results:
                text = "\n".join(r["content"] for r in results)
                parts.append(f"[{agent_name}]\n{text}")
        except Exception as exc:
            logger.debug("recall_entity_history agent=%s failed: %s", agent_name, exc)

    return "\n\n".join(parts)


def _get_entity_agent_weights(client_id: str, entity: str) -> dict[str, float]:
    """Return entity agent weights."""
    import redis as _r
    from config.settings import settings
    _redis_local = _r.from_url(settings.redis_url, decode_responses=True)

    normalized = entity.strip().lower().replace(" ", "_")[:80]
    key        = f"entity:{client_id}:{normalized}"
    data: dict = _redis_local.hgetall(key)  # type: ignore

    if not data:
        return {}

    agents_str = data.get("agents_involved", "")
    if not agents_str:
        return {}

    agents = [a for a in agents_str.split(",") if a]
    if not agents:
        return {}

    weights: dict[str, float] = {}
    for agent in agents:
        total = 0.0
        for k, v in data.items():
            if k.startswith("total_") and k.endswith("s") and not k.endswith("_amt"):
                total += float(v or 0)
        weights[agent] = max(total, 1.0)

    return weights