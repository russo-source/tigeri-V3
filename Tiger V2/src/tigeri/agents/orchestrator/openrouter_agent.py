"""OpenRouter (OpenAI-compatible) variant of the orchestrator.

Mirrors agents/orchestrator/agent.py but talks to OpenRouter via raw httpx +
SSE — no extra SDK dependency. Emits the same event stream the chat UI
consumes (agent_text / tool_call / tool_result / agent_run / done) so the
frontend stays untouched.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.orchestrator.agent import (
    SYSTEM_PROMPT,
    _summarise_agent_output,
)
from tigeri.agents.orchestrator.tools import (
    AGENT_INVOKER_TOOLS,
    REGISTRY,
    TOOL_SCHEMAS,
    WRITE_TOOLS,
    propose_write_action,
)
from tigeri.chat.budget import check_budget, record_usage, reset_window_seconds
from tigeri.chat.safety import detect_injection, scope_tool_args
from tigeri.core.config import get_settings
from tigeri.core.logging import get_logger

logger = get_logger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _to_openai_tools() -> list[dict[str, Any]]:
    """Convert Anthropic-style tool schemas to OpenAI function-calling format."""

    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_SCHEMAS
    ]


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat history from the DB is in Anthropic shape (list of content blocks).
    Flatten to plain text for OpenAI."""

    out: list[dict[str, Any]] = []
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            text_bits: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_bits.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    text_bits.append(block)
            content = "".join(text_bits)
        if role in {"user", "assistant", "system"}:
            out.append({"role": role, "content": content or ""})
    return out


def _runtime_context_preamble(tz_name: str | None = None) -> str:
    """Same as the agent.py version — see that docstring. Mirrored here so
    the openrouter path doesn't import the anthropic-loop module."""
    from datetime import UTC, datetime, timedelta

    now_utc = datetime.now(UTC)
    tomorrow_utc = now_utc + timedelta(days=1)

    local_lines = ""
    offset_hint = ""
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
            now_local = now_utc.astimezone(tz)
            tomorrow_local = tomorrow_utc.astimezone(tz)
            offset = now_local.strftime("%z")
            offset_fmt = f"{offset[:3]}:{offset[3:]}" if offset else ""
            offset_hint = (
                f" When the user gives a time without a timezone, assume "
                f"the tenant's local timezone {tz_name} ({offset_fmt}) and "
                f"emit ISO-8601 strings with that offset by default."
            )
            local_lines = (
                f"  - now (tenant {tz_name}):  "
                f"{now_local.strftime('%Y-%m-%d %H:%M:%S %z')} "
                f"(weekday: {now_local.strftime('%A')})\n"
                f"  - today (tenant):  {now_local.strftime('%Y-%m-%d')}\n"
                f"  - tomorrow (tenant): {tomorrow_local.strftime('%Y-%m-%d')}\n"
            )
        except Exception:  # noqa: BLE001
            local_lines = ""

    return (
        "RUNTIME CONTEXT (do not echo to the user, use it to ground tool args):\n"
        f"{local_lines}"
        f"  - now (UTC):       {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"(weekday: {now_utc.strftime('%A')})\n"
        f"  - today (UTC):     {now_utc.strftime('%Y-%m-%d')}\n"
        f"  - tomorrow (UTC):  {tomorrow_utc.strftime('%Y-%m-%d')}\n"
        "When the user gives a relative date ('today', 'tomorrow', 'next "
        f"Monday', 'in 2 weeks') resolve it from the values above.{offset_hint} "
        "Always emit ISO-8601 strings WITH an explicit offset (e.g. '+08:00', "
        "'+00:00'). Never ask 'what date is tomorrow?' — you already know."
    )


async def stream_chat(
    *,
    user_message: str,
    history: list[dict[str, Any]],
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    session_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """One turn of orchestrator chat against OpenRouter. Yields SSE events."""

    settings = get_settings()
    if not settings.openrouter_api_key:
        yield {"type": "agent_text", "content": "OpenRouter API key not configured.", "delta": True}
        yield {"type": "done"}
        return

    model = settings.chat_llm_model or "google/gemini-2.5-flash"

    ok, used, _remaining = await check_budget(
        session, tenant_id, daily_cap=settings.chat_tenant_daily_token_budget
    )
    if not ok:
        logger.warning(
            "chat.budget_exceeded",
            tenant_id=tenant_id,
            used=used,
            cap=settings.chat_tenant_daily_token_budget,
        )
        yield {
            "type": "agent_text",
            "content": (
                f"Daily LLM budget reached ({used:,} tokens). Resets in "
                f"{reset_window_seconds() // 3600}h."
            ),
            "delta": False,
        }
        yield {"type": "done"}
        return

    if (pat := detect_injection(user_message)):
        logger.warning(
            "chat.injection_attempt",
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            pattern=pat,
        )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.public_api_base_url,
        "X-Title": "Tigeri.ai",
    }

    tools = _to_openai_tools()
    # Tenant timezone for ISO-8601 grounding. Failure to resolve falls back
    # to UTC-only via the helper's None-tz path; never blocks the request.
    try:
        from tigeri.tenant.preferences import get_timezone

        tz_name = await get_timezone(session, tenant_id)
    except Exception:  # noqa: BLE001
        tz_name = None
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _runtime_context_preamble(tz_name)},
    ]
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": user_message})

    public_base = settings.public_api_base_url

    for _round in range(6):  # safety cap
        body = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "max_tokens": 2048,
        }

        # Accumulators for the streamed assistant turn
        text_buf = ""
        tool_calls_acc: dict[int, dict[str, Any]] = {}  # index → {id, name, arguments}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=120.0)) as client:
            async with client.stream("POST", OPENROUTER_URL, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    detail = await resp.aread()
                    yield {
                        "type": "agent_text",
                        "content": f"OpenRouter error {resp.status_code}: {detail.decode('utf-8', 'ignore')[:400]}",
                        "delta": True,
                    }
                    yield {"type": "done"}
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        evt = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if (u := evt.get("usage")):
                        usage = u
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if (fr := choices[0].get("finish_reason")) is not None:
                        finish_reason = fr

                    # Streaming text delta
                    if (txt := delta.get("content")):
                        text_buf += txt
                        yield {"type": "agent_text", "content": txt, "delta": True}

                    # Tool-call deltas (id, name, arguments come in pieces)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tool_calls_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if (args_delta := fn.get("arguments")) is not None:
                            slot["arguments"] += args_delta

        # Record token usage best-effort. OpenRouter only emits `usage` on
        # the final chunk when ``stream_options.include_usage=true`` is set,
        # so we may legitimately have None — that's fine, the record just
        # gets skipped and the budget gate continues to work for everything
        # we can see.
        if usage:
            try:
                await record_usage(
                    session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or 0),
                    model=model,
                    session_id=session_id,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("chat.usage_record_failed", error=str(e))

        if not tool_calls_acc:
            # Persist text-only assistant turn
            messages.append({"role": "assistant", "content": text_buf or None})
            break

        # Same intent-guard as the Anthropic path: drop write tool calls
        # when the user message reads as a pure lookup. Apply this BEFORE
        # we record the assistant turn — otherwise the persisted history
        # would carry tool_call ids without matching tool_result messages
        # and the next round would fail with "tool_call_id not found".
        from tigeri.agents.orchestrator.intent_guard import filter_tool_calls

        ordered = sorted(tool_calls_acc.items())
        names_in_order = [slot["name"] for _, slot in ordered]
        keep_idx, suppression = filter_tool_calls(
            user_message=user_message,
            tool_names=names_in_order,
            write_tools=WRITE_TOOLS,
        )
        if suppression:
            logger.warning(
                "chat.write_tool_suppressed",
                tenant_id=tenant_id,
                user_id=user_id,
                reason=suppression,
            )
        keep_set = set(keep_idx)
        ordered = [pair for i, pair in enumerate(ordered) if i in keep_set]

        # Persist assistant turn — only the tool_calls we actually honor
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": text_buf or None}
        if ordered:
            assistant_msg["tool_calls"] = [
                {
                    "id": slot["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {
                        "name": slot["name"],
                        "arguments": slot["arguments"] or "{}",
                    },
                }
                for idx, slot in ordered
            ]
        messages.append(assistant_msg)

        if not ordered:
            # Every tool call was suppressed → nothing left to execute,
            # bail out cleanly.
            break

        # Execute each tool, emit events, feed results back as role=tool messages
        proposed_any = False
        for idx, slot in ordered:
            tool_name = slot["name"]
            try:
                args_obj = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args_obj = {}

            scoped_args, refusal = scope_tool_args(
                args_obj, tenant_id=tenant_id, user_id=user_id
            )
            if refusal:
                # Forbidden key (role escalation, cross-tenant override)
                logger.warning(
                    "chat.tool_args_refused",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tool=tool_name,
                    reason=refusal,
                )
                payload = {"error": f"args refused: {refusal}"}
                yield {"type": "tool_call", "id": slot["id"], "tool": tool_name, "args": args_obj}
                yield {"type": "tool_result", "id": slot["id"], "ok": False, "result": payload}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": slot["id"] or f"call_{idx}",
                        "content": json.dumps({"ok": False, "result": payload})[:6000],
                    }
                )
                continue

            yield {
                "type": "tool_call",
                "id": slot["id"],
                "tool": tool_name,
                "args": scoped_args,
            }

            # Write actions go through the propose -> confirm gate.
            if tool_name in WRITE_TOOLS:
                try:
                    proposal = await propose_write_action(
                        tool_name=tool_name,
                        args=scoped_args,
                        db_session=session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        conversation_id=None,
                    )
                except Exception as e:  # noqa: BLE001
                    # Don't let propose errors silently kill the SSE stream —
                    # surface them as a tool_result so the chat UI can render
                    # the failure instead of getting stuck on tool_running.
                    logger.exception(
                        "chat.propose_failed",
                        tenant_id=tenant_id,
                        tool=tool_name,
                        error=f"{type(e).__name__}: {e}",
                    )
                    payload = {"error": f"propose failed: {type(e).__name__}: {e}"}
                    yield {
                        "type": "tool_result",
                        "id": slot["id"],
                        "ok": False,
                        "result": payload,
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": slot["id"] or f"call_{idx}",
                            "content": json.dumps({"ok": False, "result": payload})[:6000],
                        }
                    )
                    continue
                proposal["tool_use_id"] = slot["id"]
                yield proposal
                proposed_any = True
                continue

            fn = REGISTRY.get(tool_name)
            if fn is None:
                payload = {"error": f"unknown tool {tool_name}"}
                ok = False
            else:
                try:
                    payload = await fn(
                        scoped_args,
                        session=session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        session_id=session_id,
                        public_base_url=public_base,
                    )
                    # Same graceful-error-payload treatment as the
                    # Anthropic agent: a tool that returns
                    # ``{"error": "..."}`` is a failure even though it
                    # didn't raise — surface that in the chat card.
                    ok = not (
                        isinstance(payload, dict) and payload.get("error")
                    )
                except Exception as e:  # noqa: BLE001
                    payload = {"error": f"{type(e).__name__}: {e}"}
                    ok = False

            yield {
                "type": "tool_result",
                "id": slot["id"],
                "ok": ok,
                "result": payload,
            }

            if tool_name in AGENT_INVOKER_TOOLS and ok:
                agent_id = payload.get("agent_id", tool_name.removeprefix("invoke_"))
                yield {
                    "type": "agent_run",
                    "agent_id": agent_id,
                    "capabilities": payload.get("capabilities", []),
                    "trace_id": payload.get("trace_id", ""),
                    "summary": _summarise_agent_output(agent_id, payload.get("output", {})),
                }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": slot["id"] or f"call_{idx}",
                    "content": json.dumps({"ok": ok, "result": payload})[:6000],
                }
            )

        if proposed_any or (finish_reason and finish_reason != "tool_calls"):
            break

    yield {"type": "done"}
