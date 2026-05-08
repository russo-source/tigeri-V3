"""Chat endpoints: streaming SSE, history load, feedback capture."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import re

from tigeri.agents.orchestrator.agent import stream_chat as _stream_anthropic
from tigeri.agents.orchestrator.openrouter_agent import stream_chat as _stream_openrouter
from tigeri.api.deps import get_session, get_tenant_id  # noqa: F401  (kept for back-compat re-export)
from tigeri.auth.admin import require_admin
from tigeri.auth.scope import TenantScope, get_scope
from tigeri.chat import file_extract, store
from tigeri.chat.models import ChatFeedback, ChatMessage, ChatThread
from tigeri.core.config import get_settings
from tigeri.core.ids import new_id


# Client-supplied chat-thread discriminator. Sticking it raw into a DB
# index column would let a malicious client send a megabyte string and
# wreck the index. Allow only safe characters and cap length.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validated_session_id(raw: str) -> str:
    s = (raw or "default").strip()
    if not _SESSION_ID_RE.match(s):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X-Tigeri-Session-Id must match [A-Za-z0-9_-]{1,64}",
        )
    return s


def stream_chat(*args, **kwargs):
    """Dispatch to the configured chat LLM provider (anthropic | openrouter)."""

    provider = (get_settings().chat_llm_provider or "anthropic").lower()
    if provider == "openrouter":
        return _stream_openrouter(*args, **kwargs)
    return _stream_anthropic(*args, **kwargs)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---- Schemas -----------------------------------------------------------


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class FeedbackRequest(BaseModel):
    message_id: str
    rating: int  # +1 or -1
    comment: str = ""


class HistoryAction(BaseModel):
    kind: str
    tool: str | None = None
    args: dict[str, Any] | None = None
    ok: bool | None = None
    summary: str | None = None
    agent_id: str | None = None
    capabilities: list[str] | None = None
    trace_id: str | None = None


class HistoryMessage(BaseModel):
    id: str
    role: str
    content: str
    actions: list[HistoryAction]
    created_at: str


class HistoryResponse(BaseModel):
    thread_id: str | None
    messages: list[HistoryMessage]


# ---- Helpers -----------------------------------------------------------


def _history_for_anthropic(history: list[ChatTurn]) -> list[dict[str, Any]]:
    return [
        {"role": h.role, "content": h.content}
        for h in history
        if h.role in {"user", "assistant"} and h.content
    ]


def _action_from_event(ev: dict, pending: dict[str, dict]) -> dict | None:
    """Convert a streaming event into a persistable action card.

    ``pending`` maps tool_use_id → action dict so a tool_result can update the
    card we already added on tool_call.
    """
    t = ev.get("type")
    if t == "tool_call":
        action = {
            "kind": "tool_running",
            "tool": ev.get("tool", ""),
            "args": ev.get("args", {}),
            "tool_use_id": ev.get("id", ""),
        }
        pending[ev.get("id", "")] = action
        return action
    if t == "tool_result":
        prev = pending.get(ev.get("id", ""))
        if prev is None:
            return None
        prev["kind"] = "tool_done"
        prev["ok"] = bool(ev.get("ok"))
        prev["summary"] = _summarise_for_history(ev.get("result"))
        return None  # mutated in place; no new card
    if t == "agent_run":
        return {
            "kind": "agent_run",
            "agent_id": ev.get("agent_id", ""),
            "capabilities": ev.get("capabilities", []),
            "trace_id": ev.get("trace_id", ""),
            "summary": ev.get("summary", ""),
        }
    return None


def _summarise_for_history(result: Any) -> str:
    if isinstance(result, dict):
        if "count" in result:
            return f"{result['count']} item(s)"
        if "url" in result:
            return str(result["url"])
        if "trace_id" in result:
            return f"trace {str(result['trace_id'])[:18]}"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    return ""


def _hydrate_actions(actions_json: dict | list | None) -> list[HistoryAction]:
    raw: list = []
    if isinstance(actions_json, dict):
        raw = actions_json.get("items", []) or []
    elif isinstance(actions_json, list):
        raw = actions_json
    out: list[HistoryAction] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        out.append(
            HistoryAction(
                kind=a.get("kind", ""),
                tool=a.get("tool"),
                args=a.get("args") if isinstance(a.get("args"), dict) else None,
                ok=a.get("ok"),
                summary=a.get("summary"),
                agent_id=a.get("agent_id"),
                capabilities=a.get("capabilities"),
                trace_id=a.get("trace_id"),
            )
        )
    return out


# ---- Streaming chat ---------------------------------------------------


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(get_scope),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> StreamingResponse:
    """Stream a chat turn.

    Tenant + user resolve from the cookie session (preferred). Header-only
    legacy clients still work via get_scope's fallback path. ``X-Tigeri-Session-Id``
    is kept as the chat-thread discriminator so a user can split conversations
    across tabs or devices without losing history."""
    if not body.message.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "message is required")

    session_id = _validated_session_id(x_tigeri_session_id)
    tenant_id = scope.tenant_id
    user_id = scope.user_id

    thread = await store.get_or_create_thread(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )
    await store.save_user_message(
        session,
        thread_id=thread.id,
        tenant_id=tenant_id,
        content=body.message,
    )
    assistant_message_id = new_id("msg")

    async def event_stream() -> AsyncIterator[bytes]:
        text_parts: list[str] = []
        actions: list[dict] = []
        pending: dict[str, dict] = {}

        # Up-front: tell the client what message id this assistant turn will own,
        # so the thumbs-up button can submit feedback against it.
        first = {"type": "assistant_message_id", "id": assistant_message_id}
        yield f"data: {json.dumps(first)}\n\n".encode("utf-8")

        try:
            async for ev in stream_chat(
                user_message=body.message,
                history=_history_for_anthropic(body.history),
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            ):
                if ev.get("type") == "agent_text":
                    text_parts.append(ev.get("content", ""))
                else:
                    new_action = _action_from_event(ev, pending)
                    if new_action is not None:
                        actions.append(new_action)
                yield f"data: {json.dumps(ev, default=str)}\n\n".encode("utf-8")

            await store.save_assistant_message(
                session,
                thread_id=thread.id,
                tenant_id=tenant_id,
                message_id=assistant_message_id,
                content="".join(text_parts),
                actions=actions,
                model=get_settings().llm_agent_model,
                prompt_version="orchestrator/system@1.0.0",
                agent_name="orchestrator",
            )
            await session.commit()
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            err = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(err)}\n\n".encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---- History load -----------------------------------------------------


@router.get("/history", response_model=HistoryResponse)
async def chat_history(
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(get_scope),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> HistoryResponse:
    session_id = _validated_session_id(x_tigeri_session_id)
    thread = await session.scalar(
        select(ChatThread).where(
            ChatThread.tenant_id == scope.tenant_id,
            ChatThread.user_id == scope.user_id,
            ChatThread.session_id == session_id,
        )
    )
    if thread is None:
        return HistoryResponse(thread_id=None, messages=[])

    rows: list[ChatMessage] = await store.list_messages(session, thread.id)
    return HistoryResponse(
        thread_id=thread.id,
        messages=[
            HistoryMessage(
                id=m.id,
                role=m.role,
                content=store.decrypted_content(m),
                actions=_hydrate_actions(m.actions_json),
                created_at=m.created_at.isoformat(),
            )
            for m in rows
        ],
    )


# ---- Clear history -----------------------------------------------------


@router.delete("/history")
async def clear_history(
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(get_scope),
    x_tigeri_session_id: str = Header(default="default", alias="X-Tigeri-Session-Id"),
) -> dict:
    """Wipe all chat messages + feedback for the current (tenant, user, session) thread."""
    session_id = _validated_session_id(x_tigeri_session_id)
    thread = await session.scalar(
        select(ChatThread).where(
            ChatThread.tenant_id == scope.tenant_id,
            ChatThread.user_id == scope.user_id,
            ChatThread.session_id == session_id,
        )
    )
    if thread is None:
        return {"cleared": True, "messages_deleted": 0}
    msg_ids = [m.id for m in await store.list_messages(session, thread.id)]
    if msg_ids:
        await session.execute(
            delete(ChatFeedback).where(ChatFeedback.message_id.in_(msg_ids))
        )
    await session.execute(
        delete(ChatMessage).where(ChatMessage.thread_id == thread.id)
    )
    await session.execute(delete(ChatThread).where(ChatThread.id == thread.id))
    await session.commit()
    return {"cleared": True, "messages_deleted": len(msg_ids)}


# ---- File upload (PDF / Word) ------------------------------------------


@router.post("/upload")
async def chat_upload(
    file: UploadFile = File(...),
    _scope: TenantScope = Depends(get_scope),
) -> dict:
    """Extract plain text from an uploaded PDF / Word doc.

    Returns the extracted text so the client can prepend it to the next chat
    message as context. We don't persist the file — the orchestrator only
    sees the extracted text.
    """
    raw = await file.read()
    try:
        result = file_extract.extract(
            filename=file.filename or "upload",
            media_type=file.content_type or "",
            data=raw,
        )
    except file_extract.UnsupportedFileTypeError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    except file_extract.FileTooLargeError as e:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"failed to parse: {type(e).__name__}: {e}") from e

    return {
        "filename": result.filename,
        "media_type": result.media_type,
        "char_count": len(result.text),
        "truncated": result.truncated,
        "text": result.text,
    }


# ---- Feedback ----------------------------------------------------------


@router.post("/feedback")
async def chat_feedback(
    body: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(get_scope),
) -> dict:
    if body.rating not in (-1, 1):
        raise HTTPException(400, "rating must be +1 or -1")

    tenant_id = scope.tenant_id
    user_id = scope.user_id

    # Verify the message actually belongs to this tenant before accepting the
    # feedback. Without this check, any tenant could write feedback rows
    # against any other tenant's message_id (audit-flagged cross-tenant leak).
    msg = await session.scalar(
        select(ChatMessage).where(ChatMessage.id == body.message_id)
    )
    if msg is None:
        raise HTTPException(404, "message not found")
    if msg.tenant_id is not None and msg.tenant_id != tenant_id:
        # Pre-Phase-3b rows have tenant_id=NULL; for those we have to verify
        # via the parent thread.
        raise HTTPException(403, "message does not belong to this tenant")
    if msg.tenant_id is None:
        thread = await session.scalar(
            select(ChatThread).where(ChatThread.id == msg.thread_id)
        )
        if thread is None or thread.tenant_id != tenant_id:
            raise HTTPException(403, "message does not belong to this tenant")

    fb = await store.save_feedback(
        session,
        message_id=body.message_id,
        tenant_id=tenant_id,
        user_id=user_id,
        rating=body.rating,
        comment=body.comment,
    )
    await session.commit()
    return {"id": fb.id, "rating": fb.rating}


# ---- Admin feedback dashboard ------------------------------------------


class FeedbackItem(BaseModel):
    id: str
    rating: int
    comment: str
    tenant_id: str
    user_id: str
    created_at: str
    message_id: str
    message_preview: str
    user_message_preview: str
    actions: list[HistoryAction]


@router.get("/admin/feedback")
async def admin_feedback(
    session: AsyncSession = Depends(get_session),
    scope: TenantScope = Depends(require_admin),
    rating: int | None = None,
    limit: int = 100,
) -> list[FeedbackItem]:
    """Tenant-scoped feedback list. Admin role required — exposes every
    user's chat history previews for review. Filters by ``rating`` (+1/-1)."""
    tenant_id = scope.tenant_id

    from tigeri.chat.models import ChatFeedback

    if limit > 500:
        limit = 500

    fb_stmt = select(ChatFeedback).where(ChatFeedback.tenant_id == tenant_id)
    if rating in (-1, 1):
        fb_stmt = fb_stmt.where(ChatFeedback.rating == rating)
    fb_stmt = fb_stmt.order_by(ChatFeedback.created_at.desc()).limit(limit)
    fbs = (await session.scalars(fb_stmt)).all()
    if not fbs:
        return []

    msg_ids = [f.message_id for f in fbs]
    msgs = (
        await session.scalars(select(ChatMessage).where(ChatMessage.id.in_(msg_ids)))
    ).all()
    by_id = {m.id: m for m in msgs}

    thread_ids = list({m.thread_id for m in msgs})
    prior_users = (
        (
            await session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.thread_id.in_(thread_ids),
                    ChatMessage.role == "user",
                )
                .order_by(ChatMessage.thread_id, ChatMessage.turn_index)
            )
        ).all()
        if thread_ids
        else []
    )
    user_idx_lookup: dict[tuple[str, int], ChatMessage] = {}
    for u in prior_users:
        user_idx_lookup[(u.thread_id, u.turn_index)] = u

    items: list[FeedbackItem] = []
    for f in fbs:
        m = by_id.get(f.message_id)
        if m is None:
            continue
        prior_user = None
        for ti in range(m.turn_index - 1, -1, -1):
            cand = user_idx_lookup.get((m.thread_id, ti))
            if cand is not None:
                prior_user = cand
                break
        items.append(
            FeedbackItem(
                id=f.id,
                rating=f.rating,
                comment=f.comment or "",
                tenant_id=f.tenant_id,
                user_id=f.user_id,
                created_at=f.created_at.isoformat(),
                message_id=m.id,
                message_preview=store.decrypted_content(m)[:240],
                user_message_preview=(
                    store.decrypted_content(prior_user)[:240] if prior_user else ""
                ),
                actions=_hydrate_actions(m.actions_json),
            )
        )
    return items
