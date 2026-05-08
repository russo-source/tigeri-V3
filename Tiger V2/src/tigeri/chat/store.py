"""Chat persistence helpers.

After Phase 3b, message content is Fernet-encrypted at rest. New writes
populate `content_encrypted`; the legacy plaintext `content` column is
reserved for pre-0009 rows. ``decrypted_content()`` is the canonical
reader — it transparently handles both shapes.

If TIGERI_SECRET_ENCRYPTION_KEY is not set (e.g. in a local-only test env
without the integration credentials provisioned), writes fall back to
plaintext so the chat stays functional. A WARNING is logged once on the
first such fallback.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.chat.models import ChatFeedback, ChatMessage, ChatThread
from tigeri.core.ids import new_id
from tigeri.integrations.encryption import EncryptionUnavailable, decrypt, encrypt

_logger = logging.getLogger(__name__)
_warned_no_key = False


def _try_encrypt(plaintext: str) -> tuple[str | None, str]:
    """Returns (content_encrypted, content_plaintext_fallback).

    If encryption succeeds, plaintext_fallback is empty (we only store
    one). If the key isn't configured, returns (None, plaintext) and the
    caller writes the plaintext into `content` column instead.
    """
    global _warned_no_key
    if not plaintext:
        return None, ""
    try:
        return encrypt(plaintext), ""
    except EncryptionUnavailable:
        if not _warned_no_key:
            _logger.warning(
                "TIGERI_SECRET_ENCRYPTION_KEY missing — chat content stored "
                "as plaintext. Configure the Fernet key to enable at-rest "
                "encryption."
            )
            _warned_no_key = True
        return None, plaintext


def decrypted_content(msg: ChatMessage) -> str:
    """Read message content regardless of where it lives.

    Prefers the encrypted column; falls back to the legacy plaintext column
    when the row predates Phase 3b or encryption was disabled at write time.
    """
    if msg.content_encrypted:
        try:
            return decrypt(msg.content_encrypted)
        except Exception as e:  # noqa: BLE001
            _logger.warning(
                "decrypt failed for message %s: %s — falling back to plaintext",
                msg.id,
                e,
            )
    return msg.content or ""


async def get_or_create_thread(
    session: AsyncSession, *, tenant_id: str, user_id: str, session_id: str
) -> ChatThread:
    row = await session.scalar(
        select(ChatThread).where(
            ChatThread.tenant_id == tenant_id,
            ChatThread.user_id == user_id,
            ChatThread.session_id == session_id,
        )
    )
    if row is not None:
        return row
    row = ChatThread(
        id=new_id("thr"),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )
    session.add(row)
    await session.flush()
    return row


async def list_messages(session: AsyncSession, thread_id: str) -> list[ChatMessage]:
    rows = await session.scalars(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.turn_index)
    )
    return list(rows)


async def next_turn_index(session: AsyncSession, thread_id: str) -> int:
    rows = await session.scalars(
        select(ChatMessage.turn_index)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.turn_index.desc())
        .limit(1)
    )
    last = rows.first()
    return (last + 1) if last is not None else 0


async def save_user_message(
    session: AsyncSession,
    *,
    thread_id: str,
    tenant_id: str,
    content: str,
) -> ChatMessage:
    idx = await next_turn_index(session, thread_id)
    enc, plain = _try_encrypt(content)
    row = ChatMessage(
        id=new_id("msg"),
        thread_id=thread_id,
        tenant_id=tenant_id,
        turn_index=idx,
        role="user",
        content=plain,
        content_encrypted=enc,
        actions_json={"items": []},
    )
    session.add(row)
    await session.flush()
    return row


async def save_assistant_message(
    session: AsyncSession,
    *,
    thread_id: str,
    tenant_id: str,
    message_id: str,
    content: str,
    actions: list[dict[str, Any]],
    model: str | None = None,
    prompt_version: str | None = None,
    agent_name: str = "orchestrator",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    cost_micro_usd: int | None = None,
    grounding_verified: bool = False,
) -> ChatMessage:
    idx = await next_turn_index(session, thread_id)
    enc, plain = _try_encrypt(content)
    row = ChatMessage(
        id=message_id,
        thread_id=thread_id,
        tenant_id=tenant_id,
        turn_index=idx,
        role="assistant",
        content=plain,
        content_encrypted=enc,
        actions_json={"items": actions},
        model=model,
        prompt_version=prompt_version,
        agent_name=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_micro_usd=cost_micro_usd,
        grounding_verified=grounding_verified,
    )
    session.add(row)
    await session.flush()
    return row


async def save_feedback(
    session: AsyncSession,
    *,
    message_id: str,
    tenant_id: str,
    user_id: str,
    rating: int,
    comment: str = "",
) -> ChatFeedback:
    row = ChatFeedback(
        id=new_id("fbk"),
        message_id=message_id,
        tenant_id=tenant_id,
        user_id=user_id,
        rating=1 if rating > 0 else -1,
        comment=comment,
    )
    session.add(row)
    await session.flush()
    return row
