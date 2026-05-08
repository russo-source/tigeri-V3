"""Contain rag backend logic."""
from __future__ import annotations
import logging
import re
from typing import Optional
from memory.vector_store import get_embedding, search_similar, store_embedding

logger = logging.getLogger(__name__)

# Constant for chunk size.
CHUNK_SIZE = 500
# Constant for chunk overlap.
CHUNK_OVERLAP = 50

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_TARGET_CHUNK_TOKENS  = 400
_WORDS_PER_TOKEN = 0.75  
def store_knowledge(client_id: str, category: str, content: str) -> bool:
    """Execute store knowledge."""
    if not content or not content.strip():
        return False
    try:
        embedding = get_embedding(content)
        return store_embedding(
            table="knowledge_base",
            client_id=client_id,
            category=category,
            content=content,
            embedding=embedding,
        )
    except Exception as exc:
        logger.error("store_knowledge failed (client=%s category=%s): %s",
                     client_id, category, exc)
        return False


def retrieve_knowledge(
    client_id: str,
    query: str,
    category: Optional[str] = None,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> str:
    """Execute retrieve knowledge."""
    if not query or not query.strip():
        return ""
    try:
        query_embedding = get_embedding(query)
        results = search_similar(
            table="knowledge_base",
            client_id=client_id,
            query_embedding=query_embedding,
            top_k=top_k,
            category=category,
            min_similarity=min_similarity,
        )
        return chr(10).join(r["content"] for r in results)
    except Exception as exc:
        logger.error("retrieve_knowledge failed (client=%s category=%s): %s",
                     client_id, category, exc)
        return ""


def embed_client_profile(client_id: str, profile: dict) -> int:
    """Execute embed client profile."""
    entries = [
        f"{key}: {value}"
        for key, value in profile.items()
        if value is not None and value != ""
    ]
    if not entries:
        return 0
    stored = 0
    for entry in entries:
        if store_knowledge(client_id=client_id, category="client_profile", content=entry):
            stored += 1
    return stored


def embed_document(
    client_id: str,
    category: str,
    text: str,
    source: Optional[str] = None,
) -> int:
    """Execute embed document."""
    chunks = _chunk_text_semantic(text, client_id=client_id, category=category)
    if not chunks:
        return 0
    stored = 0
    for chunk in chunks:
        content = f"[{source}] {chunk}" if source else chunk
        if store_knowledge(client_id=client_id, category=category, content=content):
            stored += 1
    logger.debug("embed_document: %d/%d chunks stored (client=%s category=%s source=%s)",
                 stored, len(chunks), client_id, category, source)
    return stored


def retrieve_client_profile(client_id: str, query: str) -> str:
    """Execute retrieve client profile."""
    return retrieve_knowledge(
        client_id=client_id, query=query, category="client_profile", top_k=8,
    )


def _chunk_text(
    text:    str,
    size:    int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Execute chunk text."""
    return _chunk_text_semantic(text)


def _chunk_text_semantic(
    text: str,
    client_id: Optional[str] = None,
    category: Optional[str] = None,
) -> list[str]:
    """Execute chunk text semantic."""
    target_words = int(_TARGET_CHUNK_TOKENS / _WORDS_PER_TOKEN)

    if client_id and category:
        try:
            import redis as _r, json
            from config.settings import settings
            _rd = _r.from_url(settings.redis_url, decode_responses=True)
            cfg = _rd.get(f"chunk_config:{client_id}:{category}")
            if cfg:
                parsed = json.loads(cfg) # type: ignore
                target_words = int(parsed.get("target_words", target_words))
        except Exception:
            pass

    sentences = _SENTENCE_END.split(text.strip())
    if not sentences:
        return []

    chunks:  list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        s_words = len(sentence.split())
        if current_words + s_words > target_words and current:
            chunks.append(" ".join(current))
            overlap_sentences = max(1, len(current) // 7)
            current       = current[-overlap_sentences:]
            current_words = sum(len(s.split()) for s in current)

        current.append(sentence)
        current_words += s_words

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if c.strip()]