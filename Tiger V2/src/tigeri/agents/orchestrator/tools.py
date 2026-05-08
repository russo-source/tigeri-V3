"""Tool definitions for the Orchestrator agent.

The Orchestrator uses Anthropic native tool use. Each tool is a function the
LLM can call; we surface the call as an SSE event so the UI can render an
"agent action" card while the call is in flight.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agent_card.registry import get_registry
from tigeri.agents.admin.agent import AdminAgent
from tigeri.agents.admin.schemas import AdminInput, AdminSubject
from tigeri.agents.base import AgentRunContext
from tigeri.agents.booking.agent import BookingAgent
from tigeri.agents.booking.schemas import BookingInput, Participant, TimeWindow
from tigeri.agents.client_onboarding.agent import ClientOnboardingAgent
from tigeri.agents.client_onboarding.schemas import (
    COInput,
    ClientRecord,
    PrimaryContact,
)
from tigeri.agents.contract_management.agent import ContractManagementAgent
from tigeri.agents.contract_management.schemas import ContractInput
from tigeri.agents.expense.agent import ExpenseAgent
from tigeri.agents.expense.schemas import ExpenseInput
from tigeri.agents.financial_reporting.agent import FinancialReportingAgent
from tigeri.agents.financial_reporting.schemas import FRInput, Period
from tigeri.agents.invoice.graph_agent import InvoiceGraphAgent
from tigeri.agents.invoice.schemas import InvoiceDocument, InvoiceInput
from tigeri.agents.staffing.agent import StaffingAgent
from tigeri.agents.staffing.schemas import DemandWindow, StaffingInput
from tigeri.audit.record import AuditRecord


# ---- Tool schemas (Anthropic format) -----------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_agents",
        "description": (
            "List every Tigeri agent with priority, phase, trust tier, and "
            "ROI baseline. Use when the user asks 'what can you do' or which "
            "agents are available."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_recent_audit",
        "description": (
            "Return the most recent audit records for the current tenant. "
            "Use when the user wants to see what just happened or audit a trace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "maximum": 200},
                "trace_id": {"type": "string"},
            },
        },
    },
    # ---- Per-agent invokers ---------------------------------------------
    {
        "name": "invoke_invoice_agent",
        "description": (
            "Run the Invoice Agent end-to-end. Captures, extracts, validates, "
            "routes for approval, and POSTS the invoice to the tenant's connected "
            "GL (Xero when present, else stub). Use this whenever the user wants "
            "to create / raise / post / file / record an invoice — even if they "
            "only describe it conversationally. You should COMPOSE the "
            "invoice_text yourself from the fields the user gives you "
            "(vendor, total, tax, currency, invoice number, tax_rate). "
            "Defaults: currency=USD, tax=0.00, invoice=auto-generated. Do not "
            "ask for clarification if you have at least vendor and total — "
            "compose with the defaults and call the tool. The agent returns a "
            "deep link (posting_url) — when present, ALWAYS include it in your "
            "reply as a clickable markdown link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_text": {
                    "type": "string",
                    "description": (
                        "Plain-text invoice body in key:value lines. Example: "
                        "'vendor: Acme Corp\\ncurrency: INR\\ntotal: 5000.00\\n"
                        "tax: 900.00\\ntax_rate: GST 18%\\ninvoice: INV-1\\n"
                        "due: 2026-05-31'. Keys recognised: vendor, currency, "
                        "total, tax, tax_rate, invoice, po, due. "
                        "DEFAULT currency=INR (the org's base currency); only "
                        "use another if the user explicitly mentions it. "
                        "If the user gives a tax PERCENTAGE (e.g. 5%), compute "
                        "the absolute tax amount from total and ALSO set "
                        "tax_rate to the human label (e.g. 'tax_rate: 5%')."
                    ),
                }
            },
            "required": ["invoice_text"],
        },
    },
    {
        "name": "invoke_expense_agent",
        "description": (
            "Submit a receipt to the Expense Agent. Categorises against chart "
            "of accounts, runs policy check, reconciles against the card txn "
            "feed if available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "submitter_id": {"type": "string"},
                "receipt_text": {
                    "type": "string",
                    "description": (
                        "Plain-text receipt body, e.g. "
                        "'vendor: Qantas\\ncurrency: AUD\\ntotal: 480.00\\ntax: 48.00\\ninvoice: RCT-1'"
                    ),
                },
            },
            "required": ["submitter_id", "receipt_text"],
        },
    },
    {
        "name": "invoke_admin_agent",
        "description": (
            "Run an Admin Agent workflow template. Fires the right onboarding/"
            "offboarding/KYC checklist and dispatches comms (Telegram if linked)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_template_id": {
                    "type": "string",
                    "enum": [
                        "employee_onboarding_v1",
                        "employee_offboarding_v1",
                        "client_kyc_v1",
                    ],
                },
                "subject_type": {
                    "type": "string",
                    "enum": ["EMPLOYEE", "CONTRACTOR", "CLIENT"],
                },
                "subject_id": {"type": "string"},
                "initiator_id": {"type": "string"},
            },
            "required": [
                "workflow_template_id",
                "subject_type",
                "subject_id",
                "initiator_id",
            ],
        },
    },
    {
        "name": "invoke_staffing_agent",
        "description": (
            "Generate a roster across one or more venues. Reads available "
            "staff from the DB and assigns shifts; gaps are surfaced."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_ids": {"type": "array", "items": {"type": "string"}},
                "headcount_required": {"type": "integer", "default": 2},
                "shift_hours": {"type": "integer", "default": 8},
            },
            "required": ["venue_ids"],
        },
    },
    {
        "name": "invoke_booking_agent",
        "description": (
            "Create a booking (RESERVATION / INSPECTION / CLASS / MEETING) at "
            "a venue. Conflict-checks against existing bookings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_type": {
                    "type": "string",
                    "enum": ["RESERVATION", "INSPECTION", "CLASS", "MEETING"],
                },
                "venue_id": {"type": "string"},
                "start_iso": {
                    "type": "string",
                    "description": "ISO8601, e.g. 2026-04-30T10:00:00Z",
                },
                "duration_minutes": {"type": "integer", "default": 60},
                "participants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "role": {"type": "string"},
                        },
                        "required": ["id", "role"],
                    },
                },
            },
            "required": ["booking_type", "venue_id", "start_iso"],
        },
    },
    {
        "name": "invoke_financial_reporting_agent",
        "description": (
            "Generate a P&L, cashflow, or KPI dashboard report from posted "
            "invoices and expenses for a period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["PNL", "CASHFLOW", "KPI_DASHBOARD"],
                },
                "days_back": {
                    "type": "integer",
                    "default": 30,
                    "description": "Period covers (now - days_back) → now",
                },
            },
            "required": ["report_type"],
        },
    },
    {
        "name": "invoke_contract_management_agent",
        "description": (
            "Ingest a contract document. Extracts counterparty, dates, terms; "
            "computes lifecycle state (ACTIVE / EXPIRING / EXPIRED); persists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contract_text": {
                    "type": "string",
                    "description": (
                        "Plain-text contract body, e.g. "
                        "'counterparty: Acme\\neffective: 2026-01-01\\nexpiry: 2027-01-01\\nauto_renewal: true\\nvalue: 12000\\ncurrency: AUD\\npayment_terms: NET30'"
                    ),
                },
                "uploader_id": {"type": "string"},
                "counterparty_hint": {"type": "string"},
            },
            "required": ["contract_text", "uploader_id"],
        },
    },
    {
        "name": "invoke_client_onboarding_agent",
        "description": (
            "Onboard a new client: KYC/KYB checks, project plan generation, "
            "kickoff scheduling, handoff to Admin Agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "legal_name": {"type": "string"},
                "registration_id": {"type": "string"},
                "primary_contact_name": {"type": "string"},
                "primary_contact_email": {"type": "string"},
                "signed_contract_ref": {"type": "string"},
            },
            "required": [
                "legal_name",
                "registration_id",
                "primary_contact_name",
                "primary_contact_email",
                "signed_contract_ref",
            ],
        },
    },
    # ---- Integrations ---------------------------------------------------
    {
        "name": "list_integrations_status",
        "description": (
            "Show which third-party providers (Xero, QuickBooks, Google, "
            "Microsoft, PayPal, Telegram) the current tenant has connected."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_connect_url",
        "description": (
            "Return the OAuth connect URL for a specific provider (the user "
            "clicks it in their browser to start the OAuth flow)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["xero", "quickbooks", "google", "microsoft", "paypal"],
                }
            },
            "required": ["provider"],
        },
    },
    {
        "name": "send_gmail",
        "description": (
            "Send an email from the user's Gmail account. Requires Google "
            "OAuth to be connected on this tenant (gmail.send scope). The "
            "user is the sender; the message goes through their authentic "
            "Gmail address. Subject and body are required; cc/bcc/html are "
            "optional. Use only when the user explicitly asks to send an "
            "email; this is a write action and goes through the confirmation "
            "gate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "optional CC recipients",
                },
                "bcc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "optional BCC recipients",
                },
                "html": {
                    "type": "boolean",
                    "description": "true if body is HTML, false for plain text (default)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": (
            "List upcoming events on the user's primary Google Calendar in a "
            "given window. Read-only. Returns title, start, end, attendees, "
            "and Meet link (if any). Default window is the next 7 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min_iso": {
                    "type": "string",
                    "description": "ISO 8601 start of window (e.g. 2026-04-28T00:00:00Z). Defaults to now.",
                },
                "time_max_iso": {
                    "type": "string",
                    "description": "ISO 8601 end of window. Defaults to now+7d.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "1-100, default 25",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_calendar_event_with_meet",
        "description": (
            "Create a Google Calendar event on the user's primary calendar "
            "and (optionally) attach a Google Meet link. Sends invites to "
            "attendees. Requires Google OAuth. This is a write action and "
            "goes through the confirmation gate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "event title"},
                "start_iso": {
                    "type": "string",
                    "description": "ISO 8601 start (e.g. 2026-05-01T14:00:00+00:00)",
                },
                "end_iso": {
                    "type": "string",
                    "description": "ISO 8601 end",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "attendee email addresses (optional)",
                },
                "description": {"type": "string"},
                "location": {"type": "string"},
                "with_meet": {
                    "type": "boolean",
                    "description": "true to add a Google Meet link to the event (default true)",
                },
            },
            "required": ["summary", "start_iso", "end_iso"],
        },
    },
    # --- Google Maps Platform (server API key, no per-tenant OAuth) ----
    {
        "name": "geocode_address",
        "description": (
            "Forward-geocode a free-text address into latitude/longitude + "
            "canonical formatted address using Google Geocoding API. "
            "Read-only. Use for 'where is X', 'find coordinates for Y', or "
            "as a precursor to compute_travel_time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "free-text address"},
            },
            "required": ["address"],
        },
    },
    {
        "name": "find_place",
        "description": (
            "Find a real-world place (business, landmark) by free-text "
            "query using Google Places Find Place. Returns name, address, "
            "rating, open_now, place_id. Use when the user mentions a "
            "vendor / customer / venue and wants canonical info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "free-text place query, e.g. 'Acme Corp Sydney'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Current conditions and a multi-day forecast for a location. "
            "Pass either a lat/lng pair OR an address (which we'll geocode "
            "first). Use for 'what's the weather in <city>', 'will it rain "
            "on Saturday at the venue', 'should I bring a jacket'. Days is "
            "optional (1-10, default 5)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "free-text address; alternative to lat/lng",
                },
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "days": {
                    "type": "integer",
                    "description": "1-10, default 5",
                },
            },
            "required": [],
        },
    },
    {
        "name": "compute_travel_time",
        "description": (
            "Compute travel time + distance between origins and "
            "destinations using Google Distance Matrix. Each origin/dest "
            "is an address string or 'lat,lng'. Mode is one of "
            "{driving, walking, bicycling, transit}. Use for 'how far is "
            "X from Y', 'who's closest to the venue', 'is this commute "
            "feasible'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origins": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "list of origin addresses",
                },
                "destinations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "list of destination addresses",
                },
                "mode": {
                    "type": "string",
                    "enum": ["driving", "walking", "bicycling", "transit"],
                },
                "departure_time": {
                    "type": "string",
                    "description": "'now' or unix timestamp; only honoured for driving/transit",
                },
            },
            "required": ["origins", "destinations"],
        },
    },
    # --- Google Sheets + Drive (uses existing OAuth scopes) ------------
    {
        "name": "read_sheet",
        "description": (
            "Read an A1 range from a Google Sheet. Returns a 2-D array of "
            "cell values. Read-only. Use when the user wants to look up a "
            "vendor list, price sheet, or any tab they already maintain. "
            "Requires Google OAuth (spreadsheets scope, granted on Connect "
            "Google)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {
                    "type": "string",
                    "description": "the sheet ID (the long token in the Sheets URL)",
                },
                "range_a1": {
                    "type": "string",
                    "description": "A1 range, e.g. 'Sheet1!A1:E20' or just 'Sheet1' for the whole tab",
                },
            },
            "required": ["spreadsheet_id", "range_a1"],
        },
    },
    {
        "name": "append_sheet_row",
        "description": (
            "Append one or more rows to the bottom of a Google Sheet tab. "
            "Use for logging invoices, expenses, or events the user wants "
            "to track in their existing sheet. Write action — goes through "
            "the confirmation gate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range_a1": {
                    "type": "string",
                    "description": "tab name (e.g. 'Sheet1') — the API picks the next empty row",
                },
                "values": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": ["string", "number", "boolean"]},
                    },
                    "description": "rows of cell values, e.g. [['2026-04-28','ABC Ltd', 5000]]",
                },
            },
            "required": ["spreadsheet_id", "range_a1", "values"],
        },
    },
    {
        "name": "create_drive_doc",
        "description": (
            "Create a new Google Doc with the given title and HTML/text "
            "body. Use for generating reports, meeting notes, summaries "
            "the user wants to keep. Returns the file id and a webViewLink "
            "the user can click. Write action — confirmation gate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {
                    "type": "string",
                    "description": "HTML or plain text content",
                },
                "mime_type": {
                    "type": "string",
                    "enum": ["text/html", "text/plain"],
                    "description": "default text/html",
                },
                "folder_id": {
                    "type": "string",
                    "description": "optional Drive folder to put the doc in",
                },
            },
            "required": ["title", "body"],
        },
    },
]


# ---- Tool implementations ----------------------------------------------


async def list_agents(_args: dict, **_ctx: Any) -> dict:
    cards = get_registry().all()
    return {
        "count": len(cards),
        "agents": [
            {
                "agent_id": c.agent_id,
                "name": c.name,
                "priority": c.priority,
                "phase": c.phase.value,
                "status": c.status.value,
                "trust_tier": c.default_trust_tier.value,
                "roi_baseline": c.roi_baseline,
            }
            for c in cards
        ],
    }


async def list_recent_audit(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    limit = min(int(args.get("limit") or 20), 200)
    stmt = select(AuditRecord).where(AuditRecord.tenant_id == tenant_id)
    trace = args.get("trace_id")
    if trace:
        stmt = stmt.where(AuditRecord.trace_id == trace)
    stmt = stmt.order_by(AuditRecord.timestamp_utc.desc()).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return {
        "count": len(rows),
        "records": [
            {
                "timestamp_utc": r.timestamp_utc.isoformat(),
                "actor": r.actor,
                "action": r.action,
                "outcome": r.outcome,
                "target_resource": r.target_resource,
                "trace_id": r.trace_id,
            }
            for r in rows
        ],
    }


# ---- Helpers shared by every agent invoker -----------------------------


def _ctx_for(tenant_id: str, user_id: str) -> AgentRunContext:
    return AgentRunContext.new(tenant_id=tenant_id, actor=f"user:{user_id}")


def _capabilities_of(agent_id: str) -> list[str]:
    try:
        card = get_registry().get(agent_id)
        return [c.id for c in card.capabilities]
    except KeyError:
        return []


def _wrap(agent_id: str, trace_id: str, output: Any) -> dict:
    """Standard envelope around a Tigeri agent's output. The frontend reads
    ``agent_id`` + ``capabilities`` to render the visualisation card."""
    payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
    return {
        "trace_id": trace_id,
        "agent_id": agent_id,
        "capabilities": _capabilities_of(agent_id),
        "output": payload,
    }


def _parse_iso(v: str) -> datetime:
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ---- Per-agent invokers ------------------------------------------------


async def invoke_invoice_agent(
    args: dict, *, session: AsyncSession, tenant_id: str, user_id: str, session_id: str, **_: Any
) -> dict:
    text = args.get("invoice_text") or ""
    agent = InvoiceGraphAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = InvoiceInput(
        tenant_id=tenant_id,
        source="API",
        document=InvoiceDocument(media_type="text/plain", content_ref=f"inline:{text}"),
        received_at=datetime.now(UTC),
    )
    out = await agent.invoke(session, ctx, request, session_id=session_id, user_id=user_id)
    return _wrap("invoice_agent", ctx.trace_id, out)


async def invoke_expense_agent(
    args: dict, *, session: AsyncSession, tenant_id: str, user_id: str, **_: Any
) -> dict:
    text = args.get("receipt_text") or ""
    submitter = args.get("submitter_id") or user_id
    agent = ExpenseAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = ExpenseInput(
        tenant_id=tenant_id,
        submitter_id=submitter,
        image_ref=f"inline:{text}",
        captured_at=datetime.now(UTC),
    )
    out = await agent.invoke(session, ctx, request)
    return _wrap("expense_agent", ctx.trace_id, out)


async def invoke_admin_agent(
    args: dict, *, session: AsyncSession, tenant_id: str, user_id: str, **_: Any
) -> dict:
    agent = AdminAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = AdminInput(
        tenant_id=tenant_id,
        workflow_template_id=args["workflow_template_id"],
        subject=AdminSubject(type=args["subject_type"], id=args["subject_id"]),
        initiator_id=args.get("initiator_id") or user_id,
    )
    out = await agent.invoke(session, ctx, request)
    return _wrap("admin_agent", ctx.trace_id, out)


async def invoke_staffing_agent(
    args: dict, *, session: AsyncSession, tenant_id: str, user_id: str, **_: Any
) -> dict:
    venue_ids: list[str] = list(args.get("venue_ids") or [])
    headcount = int(args.get("headcount_required") or 2)
    hours = int(args.get("shift_hours") or 8)
    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=hours)
    agent = StaffingAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = StaffingInput(
        tenant_id=tenant_id,
        venue_ids=venue_ids or ["v_default"],
        period_start=start,
        period_end=end,
        demand_curve=[
            DemandWindow(
                interval_start=start,
                interval_end=end,
                headcount_required=headcount,
                skills_required=[],
            )
        ],
    )
    out = await agent.invoke(session, ctx, request)
    return _wrap("staffing_agent", ctx.trace_id, out)


async def invoke_booking_agent(
    args: dict, *, session: AsyncSession, tenant_id: str, user_id: str, **_: Any
) -> dict:
    start = _parse_iso(args["start_iso"])
    duration = int(args.get("duration_minutes") or 60)
    end = start + timedelta(minutes=duration)
    participants_raw = args.get("participants") or []
    participants = [
        Participant(id=p["id"], role=p.get("role", "attendee")) for p in participants_raw
    ]
    if not participants:
        participants = [Participant(id=user_id, role="organiser")]
    agent = BookingAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = BookingInput(
        tenant_id=tenant_id,
        booking_type=args["booking_type"],
        requested_window=TimeWindow(start=start, end=end),
        participants=participants,
        venue_id=args["venue_id"],
    )
    out = await agent.invoke(session, ctx, request)
    return _wrap("booking_agent", ctx.trace_id, out)


async def invoke_financial_reporting_agent(
    args: dict,
    *,
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    session_id: str,
    **_: Any,
) -> dict:
    days_back = int(args.get("days_back") or 30)
    end = datetime.now(UTC)
    start = end - timedelta(days=days_back)
    agent = FinancialReportingAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = FRInput(
        tenant_id=tenant_id,
        report_type=args["report_type"],
        period=Period(start=start, end=end),
    )
    out = await agent.invoke(session, ctx, request, session_id=session_id, user_id=user_id)
    return _wrap("financial_reporting_agent", ctx.trace_id, out)


async def invoke_contract_management_agent(
    args: dict,
    *,
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    session_id: str,
    **_: Any,
) -> dict:
    text = args.get("contract_text") or ""
    agent = ContractManagementAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = ContractInput(
        tenant_id=tenant_id,
        document_ref=f"inline:{text}",
        uploader_id=args.get("uploader_id") or user_id,
        counterparty_hint=args.get("counterparty_hint", ""),
    )
    out = await agent.invoke(session, ctx, request, session_id=session_id, user_id=user_id)
    return _wrap("contract_management_agent", ctx.trace_id, out)


async def invoke_client_onboarding_agent(
    args: dict,
    *,
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    session_id: str,
    **_: Any,
) -> dict:
    agent = ClientOnboardingAgent()
    ctx = _ctx_for(tenant_id, user_id)
    request = COInput(
        tenant_id=tenant_id,
        client_record=ClientRecord(
            legal_name=args["legal_name"],
            registration_id=args["registration_id"],
            primary_contact=PrimaryContact(
                name=args["primary_contact_name"], email=args["primary_contact_email"]
            ),
        ),
        signed_contract_ref=args["signed_contract_ref"],
    )
    out = await agent.invoke(session, ctx, request, session_id=session_id, user_id=user_id)
    return _wrap("client_onboarding_agent", ctx.trace_id, out)


# ---- Integrations ------------------------------------------------------


async def list_integrations_status(
    _args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    from tigeri.integrations import token_manager

    out: dict[str, dict] = {}
    for provider in ("xero", "quickbooks", "google", "microsoft", "paypal", "telegram"):
        row = await token_manager.get(session, tenant_id, provider)
        out[provider] = {
            "connected": row is not None,
            "meta": dict(row.meta_json or {}) if row else {},
        }
    return out


async def get_connect_url(
    args: dict, *, public_base_url: str, tenant_id: str, **_ctx: Any
) -> dict:
    provider = args.get("provider")
    if provider not in {"xero", "quickbooks", "google", "microsoft", "paypal"}:
        return {"error": f"unknown provider {provider}"}
    return {
        "provider": provider,
        "url": (
            f"{public_base_url}/api/v1/integrations/connect/{provider}"
            f"?tenant_id={tenant_id}"
        ),
    }


# ---- Google: Gmail + Calendar tools ------------------------------------


async def send_gmail(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    """Send mail via the user's connected Gmail. Returns the Gmail message id
    on success or a structured error if Google is not connected / consent
    is missing."""

    from tigeri.integrations.google import GoogleClient

    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = args.get("body") or ""
    if not to or not subject or not body:
        return {"error": "to, subject and body are required"}

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    # Append tenant-configured signature (if any) before sending. Empty
    # signature default = no change; admins can set one via tenant settings.
    try:
        from tigeri.tenant.preferences import get_gmail_signature

        signature = await get_gmail_signature(session, tenant_id)
    except Exception:  # noqa: BLE001
        signature = ""
    if signature:
        sep = "\n\n-- \n" if not bool(args.get("html") or False) else "<br><br>-- <br>"
        body = body.rstrip() + sep + signature

    try:
        result = await client.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=args.get("cc") or None,
            bcc=args.get("bcc") or None,
            html=bool(args.get("html") or False),
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Gmail send failed: {type(e).__name__}: {str(e)[:300]}"}

    return {
        "ok": True,
        "message_id": result.get("id", ""),
        "thread_id": result.get("threadId", ""),
        "to": to,
        "subject": subject,
    }


async def list_calendar_events(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    """Read primary-calendar events in a window. Read-only; bypasses the
    propose/confirm gate. Defaults to "now → now+7d" when caller doesn't
    pass a window."""

    from tigeri.integrations.google import GoogleClient

    now = datetime.now(UTC)
    time_min = (args.get("time_min_iso") or now.isoformat()).strip()
    time_max = (args.get("time_max_iso") or (now + timedelta(days=7)).isoformat()).strip()
    max_results = int(args.get("max_results") or 25)

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    try:
        items = await client.list_calendar_events(
            time_min_iso=time_min, time_max_iso=time_max, max_results=max_results
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Calendar list failed: {type(e).__name__}: {str(e)[:300]}"}

    summarised = []
    for it in items:
        meet = ""
        for ep in (it.get("conferenceData") or {}).get("entryPoints") or []:
            if ep.get("entryPointType") == "video":
                meet = ep.get("uri", "")
                break
        summarised.append(
            {
                "id": it.get("id", ""),
                "summary": it.get("summary", ""),
                "start": (it.get("start") or {}).get("dateTime") or (it.get("start") or {}).get("date") or "",
                "end": (it.get("end") or {}).get("dateTime") or (it.get("end") or {}).get("date") or "",
                "attendees": [a.get("email", "") for a in it.get("attendees") or []],
                "meet_link": meet,
                "html_link": it.get("htmlLink", ""),
            }
        )
    return {"count": len(summarised), "events": summarised}


async def create_calendar_event_with_meet(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    """Create a calendar event (and Meet link by default). Write action —
    invoked by /actions/confirm after the user approves the proposal."""

    from tigeri.integrations.google import CalendarEvent, GoogleClient

    summary = (args.get("summary") or "").strip()
    start_iso = (args.get("start_iso") or "").strip()
    end_iso = (args.get("end_iso") or "").strip()
    if not summary or not start_iso or not end_iso:
        return {"error": "summary, start_iso and end_iso are required"}

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    ev = CalendarEvent(
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        attendees=list(args.get("attendees") or []),
    )
    with_meet = bool(args.get("with_meet", True))

    try:
        created = await client.create_calendar_event(
            ev,
            with_meet=with_meet,
            description=args.get("description") or "",
            location=args.get("location") or "",
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Calendar create failed: {type(e).__name__}: {str(e)[:300]}"}

    meet_link = ""
    for ep in (created.get("conferenceData") or {}).get("entryPoints") or []:
        if ep.get("entryPointType") == "video":
            meet_link = ep.get("uri", "")
            break

    return {
        "ok": True,
        "event_id": created.get("id", ""),
        "html_link": created.get("htmlLink", ""),
        "meet_link": meet_link,
        "summary": summary,
        "start": start_iso,
        "end": end_iso,
        "attendees": ev.attendees,
    }


# ---- Google Maps Platform tools ----------------------------------------


async def geocode_address(args: dict, **_ctx: Any) -> dict:
    from tigeri.integrations import google_maps

    address = (args.get("address") or "").strip()
    if not address:
        return {"error": "address is required"}
    try:
        return await google_maps.geocode(address)
    except google_maps.MapsNotConfigured as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Geocoding failed: {type(e).__name__}: {str(e)[:300]}"}


async def find_place(args: dict, **_ctx: Any) -> dict:
    from tigeri.integrations import google_maps

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    try:
        return await google_maps.find_place(query)
    except google_maps.MapsNotConfigured as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Places lookup failed: {type(e).__name__}: {str(e)[:300]}"}


async def get_weather(args: dict, **_ctx: Any) -> dict:
    """Geocode if needed, then ask Google Weather for current + forecast.

    Combines current conditions and the day forecast in one tool call so
    the LLM doesn't have to chain — most weather questions ('rain on
    Saturday?') want both context (current) and lookahead (forecast)."""

    from tigeri.integrations import google_maps

    lat = args.get("lat")
    lng = args.get("lng")
    address = (args.get("address") or "").strip()
    days = int(args.get("days") or 5)

    if (lat is None or lng is None) and not address:
        return {"error": "either address or lat+lng is required"}

    try:
        if lat is None or lng is None:
            geo = await google_maps.geocode(address)
            if not geo.get("ok"):
                return {"error": geo.get("error", "geocoding failed")}
            lat = geo["lat"]
            lng = geo["lng"]
            resolved_address = geo.get("formatted_address", address)
        else:
            resolved_address = ""

        current = await google_maps.weather_current(float(lat), float(lng))
        forecast = await google_maps.weather_forecast(float(lat), float(lng), days=days)
    except google_maps.MapsNotConfigured as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Weather lookup failed: {type(e).__name__}: {str(e)[:300]}"}

    return {
        "ok": True,
        "lat": lat,
        "lng": lng,
        "resolved_address": resolved_address,
        "current": current if current.get("ok") else {"error": current.get("error")},
        "forecast": forecast.get("forecast") if forecast.get("ok") else {"error": forecast.get("error")},
    }


async def compute_travel_time(args: dict, **_ctx: Any) -> dict:
    from tigeri.integrations import google_maps

    origins = list(args.get("origins") or [])
    destinations = list(args.get("destinations") or [])
    mode = (args.get("mode") or "driving").lower()
    departure_time = args.get("departure_time")
    if not origins or not destinations:
        return {"error": "origins and destinations are both required"}
    try:
        return await google_maps.distance_matrix(
            origins, destinations, mode=mode, departure_time=departure_time
        )
    except google_maps.MapsNotConfigured as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Distance Matrix failed: {type(e).__name__}: {str(e)[:300]}"}


# ---- Google Sheets + Drive tools (OAuth, existing scopes) --------------


async def read_sheet(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    from tigeri.integrations.google import GoogleClient

    spreadsheet_id = (args.get("spreadsheet_id") or "").strip()
    range_a1 = (args.get("range_a1") or "").strip()
    if not spreadsheet_id or not range_a1:
        return {"error": "spreadsheet_id and range_a1 are required"}

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    try:
        rows = await client.read_sheet(spreadsheet_id, range_a1)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Sheets read failed: {type(e).__name__}: {str(e)[:300]}"}

    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "range": range_a1,
        "row_count": len(rows),
        "rows": rows,
    }


async def append_sheet_row(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    from tigeri.integrations.google import GoogleClient

    spreadsheet_id = (args.get("spreadsheet_id") or "").strip()
    range_a1 = (args.get("range_a1") or "").strip()
    values = args.get("values")
    if not spreadsheet_id or not range_a1 or not isinstance(values, list) or not values:
        return {"error": "spreadsheet_id, range_a1, and values (non-empty list of rows) are required"}

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    try:
        result = await client.append_sheet_row(spreadsheet_id, range_a1, values)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Sheets append failed: {type(e).__name__}: {str(e)[:300]}"}

    return {"ok": True, **result}


async def create_drive_doc(
    args: dict, *, session: AsyncSession, tenant_id: str, **_ctx: Any
) -> dict:
    from tigeri.integrations.google import GoogleClient

    title = (args.get("title") or "").strip()
    body = args.get("body") or ""
    mime_type = (args.get("mime_type") or "text/html").strip()
    folder_id = args.get("folder_id")
    if not title or not body:
        return {"error": "title and body are required"}
    if mime_type not in {"text/html", "text/plain"}:
        return {"error": f"unsupported mime_type {mime_type!r}; pick text/html or text/plain"}

    try:
        client = await GoogleClient.for_tenant(session, tenant_id)
    except ValueError as e:
        return {"error": f"Google not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Google not connected: {type(e).__name__}: {e}"}

    try:
        created = await client.create_drive_doc(
            title, body=body, mime_type=mime_type, folder_id=folder_id
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Drive create failed: {type(e).__name__}: {str(e)[:300]}"}

    return {
        "ok": True,
        "file_id": created.get("id", ""),
        "name": created.get("name", title),
        "web_view_link": created.get("webViewLink", ""),
        "mime_type": created.get("mimeType", ""),
    }


async def propose_write_action(
    *,
    tool_name: str,
    args: dict[str, Any],
    db_session: AsyncSession,
    tenant_id: str,
    user_id: str,
    conversation_id: str | None,
    channel: str = "web",
) -> dict[str, Any]:
    """Stage a write tool as a pending action and return the event payload
    the chat stream should emit instead of running the tool inline.

    The orchestrator loop checks ``WRITE_TOOLS`` and calls this when a write
    capability is requested by the LLM. The user then confirms (or cancels)
    via /actions/confirm — that endpoint resolves the same tool through
    ``tigeri.actions.dispatch_capability`` and runs it server-side.
    """
    from tigeri.actions.service import PendingActionService

    svc = PendingActionService(db_session)
    action, token = await svc.propose(
        tenant_id=tenant_id,
        user_id=user_id,
        capability=tool_name,
        parameters=args,
        diff_snapshot={"capability": tool_name, "params": args},
        conversation_id=conversation_id,
        channel=channel,
    )
    return {
        "type": "tool_proposed",
        "action_id": action.id,
        "capability": tool_name,
        "args": args,
        "diff_snapshot": action.diff_snapshot_json,
        "confirmation_token": token,
        "expires_at": action.expires_at.isoformat(),
    }


REGISTRY = {
    "list_agents": list_agents,
    "list_recent_audit": list_recent_audit,
    "invoke_invoice_agent": invoke_invoice_agent,
    "invoke_expense_agent": invoke_expense_agent,
    "invoke_admin_agent": invoke_admin_agent,
    "invoke_staffing_agent": invoke_staffing_agent,
    "invoke_booking_agent": invoke_booking_agent,
    "invoke_financial_reporting_agent": invoke_financial_reporting_agent,
    "invoke_contract_management_agent": invoke_contract_management_agent,
    "invoke_client_onboarding_agent": invoke_client_onboarding_agent,
    "list_integrations_status": list_integrations_status,
    "get_connect_url": get_connect_url,
    "send_gmail": send_gmail,
    "list_calendar_events": list_calendar_events,
    "create_calendar_event_with_meet": create_calendar_event_with_meet,
    "geocode_address": geocode_address,
    "find_place": find_place,
    "compute_travel_time": compute_travel_time,
    "get_weather": get_weather,
    "read_sheet": read_sheet,
    "append_sheet_row": append_sheet_row,
    "create_drive_doc": create_drive_doc,
}


# Tool names that wrap a Tigeri agent — orchestrator emits an ``agent_run``
# visualization event for each.
AGENT_INVOKER_TOOLS: set[str] = {
    "invoke_invoice_agent",
    "invoke_expense_agent",
    "invoke_admin_agent",
    "invoke_staffing_agent",
    "invoke_booking_agent",
    "invoke_financial_reporting_agent",
    "invoke_contract_management_agent",
    "invoke_client_onboarding_agent",
}


# Tools that perform writes against external systems (Xero, Telegram, etc.)
# or create persisted state. These go through the propose -> confirm gate
# (see tigeri.actions.PendingActionService) instead of running inline.
# Read-only tools (list_agents, list_recent_audit, list_integrations_status,
# get_connect_url, invoke_financial_reporting_agent) bypass the gate.
WRITE_TOOLS: set[str] = {
    "invoke_invoice_agent",
    "invoke_expense_agent",
    "invoke_admin_agent",
    "invoke_staffing_agent",
    "invoke_booking_agent",
    "invoke_contract_management_agent",
    "invoke_client_onboarding_agent",
    "send_gmail",
    "create_calendar_event_with_meet",
    "append_sheet_row",
    "create_drive_doc",
}
