"use client";

import { CheckCircle2, ChevronRight, Loader2, XCircle } from "lucide-react";

import { CalendarEventsList, PlaceCard, type PlaceLike } from "./PlaceCard";

export type ActionState =
  | { kind: "tool_running"; tool: string; args: Record<string, unknown> }
  | {
      kind: "tool_done";
      tool: string;
      args: Record<string, unknown>;
      ok: boolean;
      summary: string;
      // Raw tool result, kept around so tools that have a richer
      // visualization (find_place → embedded map, list_calendar_events →
      // event list) can render it. Optional because legacy event payloads
      // didn't carry it; do not assume non-null.
      result?: unknown;
    }
  | {
      kind: "agent_run";
      agent_id: string;
      capabilities: string[];
      trace_id: string;
      summary: string;
    };

const TOOL_LABELS: Record<string, string> = {
  list_agents: "Loading agent catalog",
  list_recent_audit: "Querying audit log",
  invoke_invoice_agent: "Invoking Invoice Agent",
  list_integrations_status: "Checking integration status",
  get_connect_url: "Fetching connect URL",
  // Maps + Workspace tools
  find_place: "Finding place on Google Maps",
  geocode_address: "Geocoding address",
  compute_travel_time: "Computing travel time",
  get_weather: "Looking up weather",
  list_calendar_events: "Listing calendar events",
  read_sheet: "Reading Google Sheet",
  send_gmail: "Sending email",
  create_calendar_event_with_meet: "Creating calendar event",
  append_sheet_row: "Appending Sheet row",
  create_drive_doc: "Creating Google Doc",
};

const AGENT_LABEL: Record<string, string> = {
  invoice_agent: "Invoice Agent",
  expense_agent: "Expense Agent",
  admin_agent: "Admin Agent",
  staffing_agent: "Staffing Agent",
  booking_agent: "Booking Agent",
  financial_reporting_agent: "Financial Reporting Agent",
  contract_management_agent: "Contract Management Agent",
  client_onboarding_agent: "Client Onboarding Agent",
};

export function AgentActionCard({ action }: { action: ActionState }) {
  if (action.kind === "tool_running") {
    return (
      <div className="my-2 flex items-start gap-2 rounded-md border border-border bg-surface-blue px-3 py-2">
        <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-navy" />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-text-primary">
            {TOOL_LABELS[action.tool] ?? action.tool}
          </div>
          <ArgsLine args={action.args} />
        </div>
      </div>
    );
  }

  if (action.kind === "tool_done") {
    return (
      <div className="my-2 rounded-md border border-border bg-surface-blue px-3 py-2">
        <div className="flex items-start gap-2">
          {action.ok ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 text-success" />
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 text-text-danger" />
          )}
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium text-text-primary">
              {TOOL_LABELS[action.tool] ?? action.tool}
            </div>
            <ArgsLine args={action.args} />
            {action.summary ? (
              <p className="mt-1 text-xs text-text-secondary">{action.summary}</p>
            ) : null}
          </div>
        </div>
        {action.ok ? <ToolResultVisual tool={action.tool} result={action.result} /> : null}
      </div>
    );
  }

  // agent_run — primary card with a navy left-rail accent
  return (
    <div className="my-2 rounded-md border border-border border-l-[3px] border-l-navy bg-surface-elevated p-3">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-sm border border-navy-darker bg-navy text-white">
          <CheckCircle2 className="h-3.5 w-3.5" />
        </span>
        <div className="text-sm font-semibold text-text-primary tracking-tight">
          {AGENT_LABEL[action.agent_id] ?? action.agent_id}
        </div>
        {action.trace_id ? (
          <span className="ml-auto rounded-sm border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
            {action.trace_id.slice(0, 14)}
          </span>
        ) : null}
      </div>
      <ol className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs">
        {action.capabilities.map((cap, i) => (
          <li key={cap} className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            <span className="font-mono text-[11px] text-text-primary">{cap}</span>
            {i < action.capabilities.length - 1 ? (
              <ChevronRight className="h-3 w-3 text-text-muted" />
            ) : null}
          </li>
        ))}
      </ol>
      {action.summary ? (
        <p className="mt-2 text-xs leading-relaxed text-text-secondary">
          {action.summary}
        </p>
      ) : null}
    </div>
  );
}

/** Tool-aware rich rendering of a successful tool_result. The summary line
 *  in the tool_done card is always shown above; this component adds visual
 *  surface (embedded map, calendar list, etc.) underneath when the tool
 *  has one. Read-only by design — never re-runs the tool.
 *
 *  Supported tools today:
 *  - find_place / geocode_address → embedded Google Maps + place card
 *  - list_calendar_events → small list of upcoming events
 */
function ToolResultVisual({
  tool,
  result,
}: {
  tool: string;
  result: unknown;
}) {
  if (!result || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;

  if (tool === "find_place" || tool === "geocode_address") {
    const place: PlaceLike = {
      ok: r.ok as boolean | undefined,
      name: typeof r.name === "string" ? r.name : undefined,
      formatted_address:
        typeof r.formatted_address === "string" ? r.formatted_address : undefined,
      place_id: typeof r.place_id === "string" ? r.place_id : undefined,
      lat: typeof r.lat === "number" ? r.lat : undefined,
      lng: typeof r.lng === "number" ? r.lng : undefined,
      rating: typeof r.rating === "number" ? r.rating : undefined,
      open_now:
        typeof r.open_now === "boolean" ? r.open_now : undefined,
      types: Array.isArray(r.types) ? (r.types as string[]) : undefined,
    };
    return <PlaceCard place={place} />;
  }

  if (tool === "list_calendar_events" && Array.isArray(r.events)) {
    return (
      <CalendarEventsList
        events={
          r.events as Array<{
            id?: string;
            summary?: string;
            start?: string;
            end?: string;
            attendees?: string[];
            meet_link?: string;
            html_link?: string;
          }>
        }
      />
    );
  }

  return null;
}


function ArgsLine({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  if (entries.length === 0) return null;
  const preview = entries
    .map(([k, v]) => {
      const sval = typeof v === "string" ? v : JSON.stringify(v);
      const trimmed = sval.length > 60 ? sval.slice(0, 60) + "…" : sval;
      return `${k}=${trimmed}`;
    })
    .join(" · ");
  return (
    <p className="mt-0.5 truncate font-mono text-[11px] text-text-secondary" title={preview}>
      {preview}
    </p>
  );
}
