"""Orchestrator agent — Claude with tool use, streamed event-by-event.

Yields a sequence of events the chat UI consumes:

    {"type": "agent_text",  "content": "..."}        # streaming partial answer
    {"type": "tool_call",   "id": "...", "tool": "...", "args": {...}}
    {"type": "tool_result", "id": "...", "ok": true, "result": {...}}
    {"type": "agent_run",   "agent_id": "...", "capabilities": [...], "trace_id": "..."}
    {"type": "done"}

The frontend renders each event as either chat content or an "agent action"
card. Tool execution + Anthropic round-trips happen here on the server.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

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


SYSTEM_PROMPT = (
    "You are Tigeri, the orchestration assistant for a business automation "
    "platform. You help SME operators run agents like Invoice, Expense, "
    "Booking, and Financial Reporting.\n\n"
    "BIAS TOWARDS ACTION. Your tools include real Tigeri agents that already "
    "have sensible defaults and validation. When in doubt, CALL THE TOOL with "
    "what the user has given you — don't ask follow-up questions for fields "
    "the agent can default. You can compose tool inputs from natural-language "
    "descriptions: e.g. 'raise an invoice to Acme for 5000' is enough to "
    "build invoice_text='vendor: Acme\\ncurrency: INR\\ntotal: 5000.00\\n"
    "tax: 0.00\\ninvoice: AUTO-<short-uuid>' and invoke. If the agent rejects "
    "with a validation error, THEN ask the user for the specific missing field.\n\n"
    "CURRENCY HANDLING: use whatever currency the user explicitly states. If "
    "they don't mention one, ASK before invoking — different Xero orgs are "
    "subscribed to different currencies, and posting in an unsupported one "
    "fails with 'Organisation is not subscribed to currency X'. If Xero "
    "rejects an invoice with that error, tell the user verbatim and offer to "
    "retry with one of {USD, GBP, EUR, AUD, NZD, CAD} — the currencies most "
    "Xero orgs support out of the box. The user can also enable additional "
    "currencies in Xero → Organisation settings → Currencies.\n\n"
    "Behaviour rules:\n"
    "1. Be concise. Default to 2–4 sentences unless the user asks for more.\n"
    "2. When the user asks you to DO something (raise/post/create an invoice, "
    "list audit, show integration status, get a connect URL, run a P&L, etc.), "
    "CALL THE MATCHING TOOL immediately. Do not narrate. Do not ask for "
    "missing fields the tool can default.\n"
    "2a. ONLY CALL TOOLS THE USER ACTUALLY ASKED FOR. If the user asks 'find "
    "me a restaurant in X' — call find_place. Do NOT also call send_gmail or "
    "create_calendar_event_with_meet — those are unrelated. Each user turn "
    "should map to ONE tool unless the user explicitly chained requests "
    "('send X an email AND schedule a meeting'). Read tools (find_place, "
    "geocode_address, get_weather, list_calendar_events, read_sheet) "
    "should NEVER trigger a write tool unless the user explicitly asks.\n"
    "3. After a tool returns, summarise what happened in plain language. "
    "Cite specific values: invoice_id, GL reference, counts, etc.\n"
    "4. If the user asks 'what can you do', call list_agents.\n"
    "5. Never fabricate audit records or invoice ids. Only state facts that "
    "came back from a tool.\n"
    "6. If a tool fails, say so plainly with the error message and suggest "
    "the next step (e.g. 'Xero is not connected; would you like me to share "
    "the connect URL?').\n"
    "7. For invoice tax given as a percentage (e.g. 5%), compute the absolute "
    "tax amount from the total before invoking, AND keep the original label "
    "(e.g. 'tax_rate: 5%') so it shows on the invoice line description.\n"
    "8. After invoke_invoice_agent succeeds, ALWAYS include the posting_url "
    "from the result as a markdown link in your reply: "
    "[View invoice in Xero](URL). Also report invoice_id and posting_reference. "
    "Do NOT email the invoice unless the user explicitly asks (e.g. 'send to "
    "rosu@example.com via email'). By default, just show the link in chat.\n\n"
    "INVOICE TEMPLATE — when the user asks to raise an invoice but gives no "
    "details, show this template and ask them to fill in:\n"
    "    Vendor: <name>           (required)\n"
    "    Total:  <amount>          (required, currency unit)\n"
    "    Tax:    <amount or %>    (optional, default 0)\n"
    "    Tax rate label: <e.g. GST 10%>  (optional)\n"
    "    Currency: <ISO-3>         (optional, default USD)\n"
    "    Invoice number: <ref>     (optional, auto-generated)\n"
    "    Due date: <YYYY-MM-DD>    (optional, default +30 days)\n"
    "    PO reference: <ref>       (optional)\n"
    "    Send by email to: <addr>  (optional — only if they want it emailed)\n\n"
    "GOOGLE WORKSPACE TOOLS — when Google is connected on this tenant, you "
    "have three additional tools:\n"
    "  - send_gmail(to, subject, body, cc?, bcc?, html?) — sends mail from "
    "the user's Gmail account. Use when the user says 'email <person> …', "
    "'send a note to …', 'follow up with … by email'. Compose subject/body "
    "yourself if the user only described the intent.\n"
    "  - list_calendar_events(time_min_iso?, time_max_iso?, max_results?) — "
    "shows upcoming events on the user's primary calendar. Use for 'what's "
    "on my calendar', 'do I have anything tomorrow', 'find a free slot'.\n"
    "  - create_calendar_event_with_meet(summary, start_iso, end_iso, "
    "attendees?, with_meet?) — creates an event AND a Meet link by default. "
    "Use for 'schedule a meeting with X tomorrow at 10', 'set up a 30-min "
    "standup with the team'. Compute start_iso/end_iso from natural "
    "language (e.g. 'tomorrow at 10am' → resolve to ISO-8601 with timezone).\n\n"
    "MEETING SCHEDULING — DO NOT BE CHATTY:\n"
    "Once you have a (summary OR rough title) AND (start time) AND (duration "
    "OR end time), CALL create_calendar_event_with_meet IMMEDIATELY. Don't "
    "ask the user to confirm dates you can compute or repeat back fields you "
    "already have. Acceptable defaults you should auto-fill:\n"
    "  - duration unspecified → 30 minutes\n"
    "  - timezone unspecified → use the offset the user implied (e.g. 'IST' "
    "    → +05:30, 'PST' → -08:00). If genuinely unspecified, use UTC.\n"
    "  - description / location unspecified → omit them; don't ask.\n"
    "  - with_meet unspecified → true.\n"
    "  - summary unspecified BUT attendee + intent given → infer a short "
    "    title like 'Intro / russo@tigeri.ai' and proceed.\n"
    "Across multiple turns, REMEMBER what the user already told you in the "
    "history. If turn N says '10:30am tomorrow' and turn N+1 says '30 mins' "
    "with title 'X', you have everything: call the tool. Do NOT re-ask for "
    "the title or the time on turn N+2.\n\n"
    "CHAINED ACTIONS:\n"
    "When the user asks 'raise an invoice AND email it to <addr>', that is "
    "TWO tool calls in one turn: invoke_invoice_agent first, then send_gmail "
    "with the result summary as the body. Don't stop after the invoice — "
    "follow up with the email tool in the same turn.\n\n"
    "All three Google tools require the tenant to have completed Google OAuth. "
    "If a call returns 'Google not connected', tell the user to go to "
    "Admin → Integrations and click Connect Google. send_gmail and "
    "create_calendar_event_with_meet are write actions — they go through "
    "the same propose-confirm gate as invoice agent posts.\n\n"
    "GOOGLE MAPS — three read-only tools that use a server API key (no "
    "OAuth needed; works as soon as the platform admin sets "
    "GOOGLE_MAPS_API_KEY):\n"
    "  - geocode_address(address) — turn an address into lat/lng + canonical "
    "form. Use as a precursor to compute_travel_time when you only have "
    "addresses.\n"
    "  - find_place(query) — look up a real business / venue by name; "
    "returns address, rating, open_now, place_id. Use when the user "
    "mentions a vendor / customer / restaurant and wants canonical info.\n"
    "  - compute_travel_time(origins, destinations, mode?) — driving / "
    "transit / walking / bicycling time + distance. Use for 'how far is X', "
    "'who's closest to the venue' (pass each candidate's address as an "
    "origin, the venue as the only destination), 'is this commute "
    "feasible'. Mode defaults to driving.\n"
    "  - get_weather(address? OR lat+lng, days?) — current conditions + "
    "1–10 day forecast. Use for 'will it rain on Saturday at the venue', "
    "'what's the weather in <city> tomorrow'. The Booking Agent should "
    "call this for outdoor venues before confirming.\n\n"
    "GOOGLE SHEETS + DRIVE — uses the same OAuth as Gmail/Calendar (drive.file "
    "+ spreadsheets scopes are already requested at Connect Google):\n"
    "  - read_sheet(spreadsheet_id, range_a1) — read a tab from one of the "
    "user's existing Sheets. Use when they ask to look up a vendor list, "
    "a price sheet, etc. Read-only.\n"
    "  - append_sheet_row(spreadsheet_id, range_a1, values) — append "
    "row(s) to a Sheet. Use to log invoices/expenses/events to a tracker "
    "the user maintains. WRITE — confirmation gate.\n"
    "  - create_drive_doc(title, body, mime_type?) — create a Google Doc "
    "with HTML or plain-text content. Use to generate reports, meeting "
    "notes, summaries. WRITE — confirmation gate.\n"
)


def _runtime_context_preamble(tz_name: str | None = None) -> str:
    """Inject the current date/time so the model can resolve relative
    dates like 'tomorrow at 10am' to ISO-8601 timestamps without asking
    the user. Without this the model has no clock and re-asks the date
    on every turn.

    ``tz_name`` is the tenant's IANA timezone (e.g. 'Asia/Singapore'). The
    preamble shows BOTH the tenant-local clock and UTC so the model can
    compose ISO-8601 strings with the right offset by default. Without a
    valid tz_name we fall back to UTC only.
    """
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
            offset = now_local.strftime("%z")  # e.g. '+0800'
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
        except Exception:  # noqa: BLE001 — bad tz string, fall through to UTC
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
    """Run one turn of orchestrator chat. Yields events for SSE."""

    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    model = settings.llm_agent_model

    ok, used, remaining = await check_budget(
        session, tenant_id, daily_cap=settings.chat_tenant_daily_token_budget
    )
    if not ok:
        # Don't call Anthropic — surface the cap to the user instead. The
        # remaining seconds let the UI show a "resets in 03:42:11" countdown.
        logger.warning(
            "chat.budget_exceeded",
            tenant_id=tenant_id,
            used=used,
            cap=settings.chat_tenant_daily_token_budget,
        )
        yield {
            "type": "agent_text",
            "content": (
                "Daily LLM budget for this tenant has been reached "
                f"({used:,} tokens). Resets in "
                f"{reset_window_seconds() // 3600}h."
            ),
            "delta": False,
        }
        yield {"type": "done"}
        return

    injection = detect_injection(user_message)
    if injection:
        # We don't refuse — Claude is better at refusing than a regex — but we
        # tag the audit stream so a flood surfaces in dashboards.
        logger.warning(
            "chat.injection_attempt",
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            pattern=injection,
        )

    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": user_message}
    ]

    public_base = settings.public_api_base_url

    # Tenant timezone for the runtime preamble. Defaulting through the
    # helper means a missing settings.timezone resolves to Asia/Singapore.
    try:
        from tigeri.tenant.preferences import get_timezone

        _tz_for_tenant = await get_timezone(session, tenant_id)
    except Exception:  # noqa: BLE001
        _tz_for_tenant = None

    # Loop: call Claude, execute any tool calls, repeat until no more tool calls.
    for _round in range(6):  # safety cap
        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    # Runtime context (current date / tomorrow / tenant tz).
                    # Not cached because it changes every turn — keeping it
                    # in its own block lets the static SYSTEM_PROMPT cache
                    # hit.
                    "text": _runtime_context_preamble(_tz_for_tenant),
                },
            ],
            tools=TOOL_SCHEMAS,
            messages=messages,
        ) as stream:
            async for event in stream:
                # Stream just the text deltas to the UI in real time
                if event.type == "content_block_delta" and getattr(
                    event.delta, "type", ""
                ) == "text_delta":
                    yield {"type": "agent_text", "content": event.delta.text, "delta": True}
            final = await stream.get_final_message()

        # Record token usage for budget tracking. Best-effort: a failed
        # write here must not break chat — if the audit table is
        # unreachable, the next /readyz will trip and ops will see it.
        try:
            usage = getattr(final, "usage", None)
            if usage is not None:
                await record_usage(
                    session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    model=model,
                    session_id=session_id,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("chat.usage_record_failed", error=str(e))

        # Find tool_use blocks; if none, persist the text turn and bail.
        tool_uses = [b for b in final.content if b.type == "tool_use"]
        if not tool_uses:
            messages.append({"role": "assistant", "content": final.content})
            break

        # Guardrail: drop spurious write tool_use calls when the user's
        # message clearly reads as a read-only lookup. See
        # tigeri.agents.orchestrator.intent_guard for rationale.
        # Filter BEFORE persisting the assistant turn — otherwise Claude
        # will see tool_use blocks in history without matching tool_result
        # messages on the next call and reject the whole conversation.
        from tigeri.agents.orchestrator.intent_guard import filter_tool_calls

        keep_idx, suppression = filter_tool_calls(
            user_message=user_message,
            tool_names=[tu.name for tu in tool_uses],
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
        kept_tool_use_ids = {tu.id for i, tu in enumerate(tool_uses) if i in keep_set}
        # Reconstruct content keeping all text blocks + only the kept tool_use
        # blocks. Anthropic content blocks are pydantic models, so we filter
        # by type+id rather than rebuilding from scratch.
        filtered_content = [
            b
            for b in final.content
            if b.type != "tool_use" or b.id in kept_tool_use_ids
        ]
        messages.append({"role": "assistant", "content": filtered_content})

        tool_uses = [tu for i, tu in enumerate(tool_uses) if i in keep_set]
        if not tool_uses:
            # All write calls were suppressed and no read tools remained
            # (rare). Nothing else to do this round.
            break

        tool_results: list[dict[str, Any]] = []
        proposed_any = False
        for tu in tool_uses:
            scoped_args, refusal = scope_tool_args(
                tu.input or {}, tenant_id=tenant_id, user_id=user_id
            )
            if refusal:
                # The model tried to set a forbidden key (role escalation,
                # cross-tenant override). Don't run the tool; surface the
                # refusal to the LLM as a tool_result so it stops trying.
                logger.warning(
                    "chat.tool_args_refused",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tool=tu.name,
                    reason=refusal,
                )
                payload = {"error": f"args refused: {refusal}"}
                yield {"type": "tool_call", "id": tu.id, "tool": tu.name, "args": tu.input}
                yield {"type": "tool_result", "id": tu.id, "ok": False, "result": payload}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": _tool_result_to_anthropic(payload, False),
                    }
                )
                continue

            yield {
                "type": "tool_call",
                "id": tu.id,
                "tool": tu.name,
                "args": scoped_args,
            }

            # Write actions go through the propose -> confirm gate. Emit the
            # proposal event, persist a pending_actions row, and end this
            # turn — execution happens via /actions/confirm.
            if tu.name in WRITE_TOOLS:
                try:
                    proposal = await propose_write_action(
                        tool_name=tu.name,
                        args=scoped_args,
                        db_session=session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        conversation_id=None,  # populated when conversations rename lands
                    )
                except Exception as e:  # noqa: BLE001
                    # An exception inside propose_write_action used to take
                    # the SSE generator down silently — chat history then
                    # forever rendered "tool_running" with no follow-up. Now
                    # we emit a real tool_result so the UI can show the
                    # failure and the user can retry.
                    logger.exception(
                        "chat.propose_failed",
                        tenant_id=tenant_id,
                        tool=tu.name,
                        error=f"{type(e).__name__}: {e}",
                    )
                    payload = {"error": f"propose failed: {type(e).__name__}: {e}"}
                    yield {
                        "type": "tool_result",
                        "id": tu.id,
                        "ok": False,
                        "result": payload,
                    }
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": _tool_result_to_anthropic(payload, False),
                        }
                    )
                    continue
                proposal["tool_use_id"] = tu.id
                yield proposal
                proposed_any = True
                continue

            fn = REGISTRY.get(tu.name)
            if fn is None:
                payload = {"error": f"unknown tool {tu.name}"}
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
                    # Tool wrappers return ``{"error": "..."}`` on graceful
                    # failures (provider returned 4xx / not connected /
                    # validation rejected) without raising. Treat that as a
                    # failure so the chat UI shows it as red and the
                    # summary line surfaces the actual reason instead of
                    # the generic "Done.".
                    ok = not (
                        isinstance(payload, dict) and payload.get("error")
                    )
                except Exception as e:  # noqa: BLE001
                    payload = {"error": f"{type(e).__name__}: {e}"}
                    ok = False

            yield {
                "type": "tool_result",
                "id": tu.id,
                "ok": ok,
                "result": payload,
            }

            # Surface a higher-level "agent_run" card whenever an actual Tigeri
            # agent invoker tool was used. Each card lists the capabilities that
            # ran (from the agent's card) and a one-line outcome summary.
            if tu.name in AGENT_INVOKER_TOOLS and ok:
                agent_id = payload.get("agent_id", tu.name.removeprefix("invoke_"))
                yield {
                    "type": "agent_run",
                    "agent_id": agent_id,
                    "capabilities": payload.get("capabilities", []),
                    "trace_id": payload.get("trace_id", ""),
                    "summary": _summarise_agent_output(agent_id, payload.get("output", {})),
                }

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": _tool_result_to_anthropic(payload, ok),
                }
            )

        # If we proposed any write action, end the turn here. The user will
        # confirm or cancel via /actions/confirm, which executes the
        # capability server-side and writes a follow-up tool_result.
        if proposed_any:
            break

        # Feed tool results back to Claude for the next iteration
        messages.append({"role": "user", "content": tool_results})

    yield {"type": "done"}


def _tool_result_to_anthropic(payload: dict, ok: bool) -> str:
    import json

    return json.dumps({"ok": ok, "result": payload})[:6000]


def _summarise_agent_output(agent_id: str, out: dict) -> str:
    """Per-agent one-liner shown on the agent_run card."""

    if not out:
        return ""
    if agent_id == "invoice_agent":
        bits = [
            f"vendor={out.get('vendor_name', '?')}",
            f"{out.get('amount_total', '?')} {out.get('currency', '')}",
        ]
        if out.get("tax_total") and str(out.get("tax_total")) not in {"0", "0.00", "0.0"}:
            bits.append(f"tax={out['tax_total']}")
        bits.extend(
            [
                f"validation={out.get('validation_status', '?')}",
                f"approval={out.get('approval_status', '?')}",
                f"posting={out.get('posting_status', '?')}",
            ]
        )
        if out.get("posting_reference"):
            bits.append(f"ref={out['posting_reference']}")
        if out.get("posting_url"):
            bits.append(f"url={out['posting_url']}")
        return " · ".join(bits)
    if agent_id == "expense_agent":
        return (
            f"{out.get('merchant', '?')} · {out.get('amount', '?')} "
            f"{out.get('currency', '')} · {out.get('category', '?')} · "
            f"policy={out.get('policy_status', '?')} · "
            f"reconciled={out.get('reconciliation_status', '?')}"
        )
    if agent_id == "admin_agent":
        return (
            f"workflow={out.get('current_step', '?')} · "
            f"status={out.get('status', '?')} · "
            f"docs={len(out.get('documents_generated', []))} · "
            f"comms={len(out.get('communications_sent', []))}"
        )
    if agent_id == "staffing_agent":
        return (
            f"shifts={len(out.get('shifts', []))} · "
            f"open_gaps={out.get('open_gap_count', '?')}"
        )
    if agent_id == "booking_agent":
        return (
            f"venue={out.get('venue_id', '?')} · "
            f"status={out.get('status', '?')} · "
            f"notified={out.get('notifications_dispatched', 0)}"
        )
    if agent_id == "financial_reporting_agent":
        kpis = out.get("kpis", []) or []
        kpi_bits = [f"{k['name']}={k['value']}" for k in kpis[:4]]
        return f"report={out.get('report_type', '?')} · " + " · ".join(kpi_bits)
    if agent_id == "contract_management_agent":
        return (
            f"counterparty={out.get('counterparty', '?')} · "
            f"expires={(out.get('expiry_date') or '?')[:10]} · "
            f"state={out.get('lifecycle_state', '?')} · "
            f"terms={len(out.get('key_terms', []))}"
        )
    if agent_id == "client_onboarding_agent":
        return (
            f"kyc={out.get('kyc_status', '?')} · "
            f"kyb={out.get('kyb_status', '?')} · "
            f"plan={out.get('project_plan_ref', '?')}"
        )
    return ""


async def _flush() -> None:  # pragma: no cover — keeps mypy happy
    await asyncio.sleep(0)
