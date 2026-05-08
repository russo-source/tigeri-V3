"use client";

import { useEffect, useState } from "react";
import { RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { api } from "@/lib/api";

type FeedbackRow = Awaited<ReturnType<typeof api.adminFeedback>>[number];
type Filter = "all" | "up" | "down";

const AGENT_LABEL: Record<string, string> = {
  invoice_agent: "Invoice",
  expense_agent: "Expense",
  admin_agent: "Admin",
  staffing_agent: "Staffing",
  booking_agent: "Booking",
  financial_reporting_agent: "Financial Reporting",
  contract_management_agent: "Contract Management",
  client_onboarding_agent: "Client Onboarding",
};

export default function AdminFeedbackPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [rows, setRows] = useState<FeedbackRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const params: { rating?: 1 | -1; limit?: number } = { limit: 200 };
      if (filter === "up") params.rating = 1;
      if (filter === "down") params.rating = -1;
      const data = await api.adminFeedback(params);
      setRows(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const totals = (() => {
    if (!rows) return { total: 0, up: 0, down: 0 };
    return {
      total: rows.length,
      up: rows.filter((r) => r.rating > 0).length,
      down: rows.filter((r) => r.rating < 0).length,
    };
  })();

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Chat feedback</h1>
          <p className="mt-1 text-sm text-text-secondary">
            Tenant-scoped helpful / not-helpful ratings users left on the assistant.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FilterPill active={filter === "all"} onClick={() => setFilter("all")}>
            All ({totals.total})
          </FilterPill>
          <FilterPill active={filter === "up"} onClick={() => setFilter("up")}>
            <ThumbsUp className="inline h-3 w-3" /> {totals.up}
          </FilterPill>
          <FilterPill active={filter === "down"} onClick={() => setFilter("down")}>
            <ThumbsDown className="inline h-3 w-3" /> {totals.down}
          </FilterPill>
          <button
            onClick={() => void refresh()}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
          >
            <RefreshCw className={"h-3 w-3 " + (busy ? "animate-spin" : "")} />
            Refresh
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">{error}</div>
      ) : null}

      {!rows ? (
        <div className="text-sm text-text-secondary">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-md border border-border bg-surface p-6 text-sm text-text-secondary">
          No feedback yet. Open the chat (bottom-right), chat with Tigeri, then rate a reply
          using the helpful / not-helpful buttons.
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <FeedbackCard key={r.id} row={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterPill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-full px-3 py-1 text-xs " +
        (active
          ? "bg-navy text-white border border-navy-darker"
          : "border border-border bg-surface text-text-secondary hover:text-text-primary")
      }
    >
      {children}
    </button>
  );
}

function FeedbackCard({ row }: { row: FeedbackRow }) {
  const isUp = row.rating > 0;
  const agentRuns = row.actions.filter((a) => a.kind === "agent_run");
  return (
    <article className="rounded-md border border-border bg-surface p-4">
      <header className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium " +
            (isUp ? "border border-success/40 bg-surface-blue text-success" : "border border-danger/40 bg-surface-blue text-text-danger")
          }
        >
          {isUp ? (
            <ThumbsUp className="h-3 w-3" />
          ) : (
            <ThumbsDown className="h-3 w-3" />
          )}
          {isUp ? "Helpful" : "Not helpful"}
        </span>
        <span className="font-mono text-text-muted">{row.created_at.slice(0, 19)}</span>
        <span className="ml-auto text-text-muted">
          user <span className="font-mono text-text-primary">{row.user_id}</span>
        </span>
      </header>

      {row.user_message_preview ? (
        <p className="mt-3 text-xs uppercase tracking-wide text-text-muted">User asked</p>
      ) : null}
      {row.user_message_preview ? (
        <blockquote className="mt-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-text-secondary">
          {row.user_message_preview}
          {row.user_message_preview.length === 240 ? "…" : ""}
        </blockquote>
      ) : null}

      <p className="mt-3 text-xs uppercase tracking-wide text-text-muted">Assistant replied</p>
      <p className="mt-1 whitespace-pre-wrap text-sm text-text-primary">
        {row.message_preview}
        {row.message_preview.length === 240 ? "…" : ""}
      </p>

      {agentRuns.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs">
          {agentRuns.map((a, i) => (
            <li key={i} className="text-text-muted">
              <span className="font-medium text-text-primary">
                {AGENT_LABEL[a.agent_id ?? ""] ?? a.agent_id} agent
              </span>
              {a.summary ? <span> · {a.summary}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {row.comment ? (
        <p className="mt-3 rounded-md border border-border bg-background px-3 py-2 text-xs italic text-text-secondary">
          “{row.comment}”
        </p>
      ) : null}

      <footer className="mt-3 text-[11px] text-text-muted">
        message id <code className="font-mono text-text-primary">{row.message_id}</code>
      </footer>
    </article>
  );
}
