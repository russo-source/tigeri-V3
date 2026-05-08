"""Contain vector store backend logic."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Optional

import redis
from redis import Redis

from config.db_pool import get_conn
from config.settings import settings

logger = logging.getLogger(__name__)

_redis: Redis = redis.from_url(settings.redis_url, decode_responses=True)

# Constant for embedding dims.
EMBEDDING_DIMS    = 1024
# Constant for embedding cache time-to-live.
EMBEDDING_CACHE_TTL = 3_600
# Constant for search cache time-to-live.
SEARCH_CACHE_TTL    = 60
# Constant for dedup cache time-to-live.
DEDUP_CACHE_TTL     = 86400 * 30

# Hybrid search weights
_VECTOR_WEIGHT = 0.70
_BM25_WEIGHT   = 0.30
# Composite ranking weights
_SIM_W      = 0.60
_RECENCY_W  = 0.25
_FREQ_W     = 0.15
# Recency half-life in days
_RECENCY_HALF_LIFE = 30.0



def _fetch_voyage_embedding(text: str) -> list[float]:
    """Retrieve voyage embedding."""
    import httpx
    resp = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={"input": text, "model": "voyage-3"},
        timeout=15,
    )
    resp.raise_for_status()
    embedding: list[float] = resp.json()["data"][0]["embedding"]
    if len(embedding) != EMBEDDING_DIMS:
        raise ValueError(f"Voyage returned {len(embedding)}-dim, expected {EMBEDDING_DIMS}")
    return embedding


def _fetch_voyage_batch(texts: list[str]) -> list[list[float]]:
    """Retrieve voyage batch."""
    import httpx
    resp = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={"input": texts, "model": "voyage-3"},
        timeout=30,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def _mock_embedding(text: str) -> list[float]:
    """Execute mock embedding."""
    hash_bytes = hashlib.md5(text.encode()).digest()
    base       = [b / 255.0 for b in hash_bytes]
    repeats    = (EMBEDDING_DIMS // len(base)) + 1
    return (base * repeats)[:EMBEDDING_DIMS]


def get_embedding(text: str) -> list[float]:
    """Return embedding."""
    cache_key = f"emb:{hashlib.md5(text.encode()).hexdigest()}"
    cached: Optional[str] = _redis.get(cache_key)  # type: ignore
    if cached:
        return json.loads(cached)

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            embedding = (
                _mock_embedding(text)
                if settings.env == "development"
                else _fetch_voyage_embedding(text)
            )
            _redis.setex(cache_key, EMBEDDING_CACHE_TTL, json.dumps(embedding))
            return embedding
        except Exception as exc:
            if "429" in str(exc) and attempt < 2:
                wait = 2 ** attempt
                logger.warning("Voyage 429 rate limit — retrying in %ds (attempt %d/3)", wait, attempt + 1)
                time.sleep(wait)
                last_exc = exc
                continue
            raise

    raise last_exc or RuntimeError("get_embedding failed after 3 attempts")


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Return embeddings batch."""
    if not texts:
        return []

    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int]           = []

    for i, text in enumerate(texts):
        key    = f"emb:{hashlib.md5(text.encode()).hexdigest()}"
        cached = _redis.get(key)
        if cached:
            results[i] = json.loads(cached)  # type: ignore
        else:
            miss_indices.append(i)

    if miss_indices:
        miss_texts = [texts[i] for i in miss_indices]
        for attempt in range(3):
            try:
                if settings.env == "development":
                    embeddings = [_mock_embedding(t) for t in miss_texts]
                else:
                    embeddings = _fetch_voyage_batch(miss_texts)

                for idx, emb in zip(miss_indices, embeddings):
                    key = f"emb:{hashlib.md5(texts[idx].encode()).hexdigest()}"
                    _redis.setex(key, EMBEDDING_CACHE_TTL, json.dumps(emb))
                    results[idx] = emb
                break

            except Exception as exc:
                if "429" in str(exc) and attempt < 2:
                    wait = 2 ** attempt
                    logger.warning("Voyage batch 429 — retrying in %ds (attempt %d/3)", wait, attempt + 1)
                    time.sleep(wait)
                    continue
                logger.warning("Batch embedding failed, falling back to sequential: %s", exc)
                for idx in miss_indices:
                    try:
                        results[idx] = get_embedding(texts[idx])
                    except Exception as seq_exc:
                        logger.warning("Sequential embedding fallback failed idx=%d: %s", idx, seq_exc)
                break

    return [r for r in results if r is not None]


def _vec(embedding: list[float]) -> str:
    """Execute vec."""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def store_embedding(
    table: str,
    client_id: str,
    content: str,
    embedding: list[float],
    agent_name: Optional[str] = None,
    category: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """Execute store embedding."""
    content_hash = hashlib.md5(content.encode()).hexdigest()
    dedup_key = f"emb_stored:{table}:{client_id}:{content_hash}"
    if _redis.exists(dedup_key):
        return False
    vec = _vec(embedding)
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if table == "agent_memory":
                cur.execute(
                    "INSERT INTO agent_memory (client_id, agent_name, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector) ON CONFLICT DO NOTHING",
                    (client_id, agent_name, content, vec),
                )
            elif table == "knowledge_base":
                cur.execute(
                    "INSERT INTO knowledge_base (client_id, category, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector) ON CONFLICT DO NOTHING",
                    (client_id, category, content, vec),
                )
            else:
                cur.close()
                raise ValueError(f"Unknown vector table: {table!r}")
            cur.close()
    except Exception as exc:
        logger.error("store_embedding failed (table=%s client=%s): %s",
                     table, client_id, exc, exc_info=True)
        raise

    _redis.setex(dedup_key, DEDUP_CACHE_TTL, "1")

    freq_key = f"emb_freq:{table}:{client_id}:{content_hash}"
    _redis.incr(freq_key)
    _redis.expire(freq_key, 86400 * 365)

    return True


def search_similar(
    table: str,
    client_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    agent_name: Optional[str] = None,
    category: Optional[str] = None,
    min_similarity: float = 0.0,
) -> list[dict]:
    """Execute search similar."""
    vec_sig   = hashlib.md5(str(query_embedding[:8]).encode()).hexdigest()
    cache_key = f"search:{table}:{client_id}:{agent_name or category or 'all'}:{vec_sig}"
    cached: Optional[str] = _redis.get(cache_key)  # type: ignore
    if cached:
        return json.loads(cached)

    effective_min = max(min_similarity, 0.25)
    vec     = _vec(query_embedding)
    results = _run_search(table, client_id, vec, top_k * 2, agent_name, category, effective_min)

    results = _apply_composite_score(results, client_id, table)

    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    results = results[:top_k]

    if min_similarity > 0:
        results = [r for r in results if r.get("similarity", 0.0) >= min_similarity]

    _redis.setex(cache_key, SEARCH_CACHE_TTL, json.dumps(results))
    return results


def _recency_weight(created_at_str: str) -> float:
    """Execute recency weight."""
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - created).days
        return math.exp(-math.log(2) * days / _RECENCY_HALF_LIFE)
    except Exception:
        return 0.5


def _apply_composite_score(
    results: list[dict], client_id: str, table: str
) -> list[dict]:
    """Execute apply composite score."""
    for r in results:
        sim          = r.get("similarity", 0.0)
        recency      = _recency_weight(r.get("created_at", ""))
        content_hash = hashlib.md5((r.get("content") or "").encode()).hexdigest()
        freq_raw     = _redis.get(f"emb_freq:{table}:{client_id}:{content_hash}")
        freq         = min(int(freq_raw or 1) / 10.0, 1.0)  # type: ignore
        r["score"]   = _SIM_W * sim + _RECENCY_W * recency + _FREQ_W * freq
    return results


def _run_search(
    table: str,
    client_id: str,
    vec: str,
    top_k: int,
    agent_name: Optional[str],
    category: Optional[str],
    min_similarity: float = 0.25,
) -> list[dict]:
    """Run search."""
    with get_conn() as conn:
        cur = conn.cursor()

        if table == "agent_memory":
            cur.execute(
                "SELECT content, agent_name, created_at, "
                "       1 - (embedding <=> %s::vector) AS similarity "
                "FROM agent_memory "
                "WHERE client_id = %s AND (%s IS NULL OR agent_name = %s) "
                "  AND 1 - (embedding <=> %s::vector) >= %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, client_id, agent_name, agent_name, vec, min_similarity, vec, top_k),
            )
        elif table == "knowledge_base":
            cur.execute(
                "SELECT content, category, created_at, "
                "       1 - (embedding <=> %s::vector) AS similarity "
                "FROM knowledge_base "
                "WHERE client_id = %s AND (%s IS NULL OR category = %s) "
                "  AND 1 - (embedding <=> %s::vector) >= %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, client_id, category, category, vec, min_similarity, vec, top_k),
            )
        else:
            cur.close()
            raise ValueError(f"Unknown vector table: {table!r}")

        vector_rows = cur.fetchall()
        vector_results = [
            {"content": r[0], "meta": r[1], "created_at": str(r[2]),
             "similarity": float(r[3]) if r[3] is not None else 0.0}
            for r in vector_rows
        ]

        trgm_results: list[dict] = []
        if vector_results:
            pivot = vector_results[0]["content"][:200]
            try:
                if table == "agent_memory":
                    cur.execute(
                        "SELECT content, agent_name, created_at, "
                        "       similarity(content, %s) AS trgm_score "
                        "FROM agent_memory "
                        "WHERE client_id = %s AND (%s IS NULL OR agent_name = %s) "
                        "  AND similarity(content, %s) > 0.1 "
                        "ORDER BY trgm_score DESC LIMIT %s",
                        (pivot, client_id, agent_name, agent_name, pivot, top_k),
                    )
                else:
                    cur.execute(
                        "SELECT content, category, created_at, "
                        "       similarity(content, %s) AS trgm_score "
                        "FROM knowledge_base "
                        "WHERE client_id = %s AND (%s IS NULL OR category = %s) "
                        "  AND similarity(content, %s) > 0.1 "
                        "ORDER BY trgm_score DESC LIMIT %s",
                        (pivot, client_id, category, category, pivot, top_k),
                    )
                trgm_rows = cur.fetchall()
                trgm_results = [
                    {"content": r[0], "meta": r[1], "created_at": str(r[2]),
                     "similarity": float(r[3]) if r[3] is not None else 0.0}
                    for r in trgm_rows
                ]
            except Exception as trgm_exc:
                logger.debug("pg_trgm search unavailable, using pure vector: %s", trgm_exc)

        cur.close()

    if not trgm_results:
        return vector_results

    K = 60
    rrf_scores: dict[str, float] = {}
    content_map: dict[str, dict] = {}

    for rank, r in enumerate(vector_results):
        key = r["content"][:100]
        rrf_scores[key]  = rrf_scores.get(key, 0.0) + _VECTOR_WEIGHT / (K + rank + 1)
        content_map[key] = r

    for rank, r in enumerate(trgm_results):
        key = r["content"][:100]
        rrf_scores[key]  = rrf_scores.get(key, 0.0) + _BM25_WEIGHT / (K + rank + 1)
        if key not in content_map:
            content_map[key] = r

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [content_map[key] for key, _ in merged[:top_k]]


_CONF_PRIOR_ALPHA = 7.0
_CONF_PRIOR_BETA  = 3.0
_GLOBAL_DEFAULT   = 0.70


def get_confidence_threshold(client_id: str, intent: str) -> float:
    """Return confidence threshold."""
    try:
        beta_key = f"conf_beta:{client_id}:{intent}"
        raw      = _redis.hmget(beta_key, ["alpha", "beta"])  # type: ignore
        alpha    = float(raw[0]) if raw[0] else None  # type: ignore
        beta     = float(raw[1]) if raw[1] else None  # type: ignore

        if alpha is not None and beta is not None:
            denom = alpha + beta - 2
            return float((alpha - 1) / denom) if denom > 0 else alpha / (alpha + beta)

        val = _redis.get(f"conf_threshold:{client_id}:{intent}")
        return float(val) if val else _GLOBAL_DEFAULT  # type: ignore

    except Exception:
        return _GLOBAL_DEFAULT


def set_confidence_threshold(
    client_id: str,
    intent:    str,
    value:     float,
    ttl:       int = 86400 * 30,
) -> None:
    """Set confidence threshold."""
    key = f"conf_threshold:{client_id}:{intent}"
    _redis.set(key, str(value))
    _redis.expire(key, ttl)
    alpha = round(value * 12)
    beta  = round((1 - value) * 12)
    _redis.hset(f"conf_beta:{client_id}:{intent}", mapping={"alpha": alpha, "beta": beta})
    _redis.expire(f"conf_beta:{client_id}:{intent}", ttl)


def update_confidence_posterior(
    client_id: str,
    intent:    str,
    success:   bool,
) -> None:
    """Update confidence posterior."""
    beta_key = f"conf_beta:{client_id}:{intent}"
    raw      = _redis.hmget(beta_key, ["alpha", "beta"])  # type: ignore
    alpha    = float(raw[0]) if raw[0] else _CONF_PRIOR_ALPHA  # type: ignore
    beta_val = float(raw[1]) if raw[1] else _CONF_PRIOR_BETA   # type: ignore

    if success:
        alpha += 1.0
    else:
        beta_val += 1.0

    _redis.hset(beta_key, mapping={"alpha": alpha, "beta": beta_val})
    _redis.expire(beta_key, 86400 * 30)