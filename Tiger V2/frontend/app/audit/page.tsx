"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { AuditRecord } from "@/lib/type";

export default function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [traceFilter, setTraceFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");

  async function refresh() {
    setError(null);
    try {
      const rows = await api.listAudit({
        trace_id: traceFilter || undefined,
        actor: actorFilter || undefined,
        limit: 200,
      });
      setRecords(rows);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
          <p className="mt-1 text-xs text-text-muted">
            Local append-only buffer.{" "}
            <code>chain_position</code> + <code>backfilled_at</code> populate
            once Compliance &amp; Audit Agent (Priority 12) is live.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="actor (e.g. invoice_agent:api)"
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-text-primary outline-none transition-colors focus:border-navy"
          />
          <input
            value={traceFilter}
            onChange={(e) => setTraceFilter(e.target.value)}
            placeholder="trace_id"
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-text-primary outline-none transition-colors focus:border-navy"
          />
          <button
            onClick={() => void refresh()}
            className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-navy-dark"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
          {error}
        </div>
      ) : null}

      {!records ? (
        <div className="text-sm text-text-secondary">Loading…</div>
      ) : records.length === 0 ? (
        <div className="rounded-md border border-border bg-surface p-6 text-sm text-text-secondary">
          No records.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-surface">
          <table className="w-full text-xs">
            <thead className="text-text-muted">
              <tr className="text-left">
                <th className="px-3 py-2">Timestamp (UTC)</th>
                <th className="px-3 py-2">Actor</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Outcome</th>
                <th className="px-3 py-2">Target</th>
                <th className="px-3 py-2">Trace</th>
                <th className="px-3 py-2">Chain</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.id} className="border-t border-border-5">
                  <td className="px-3 py-1.5 font-mono">
                    {r.timestamp_utc.slice(0, 19)}
                  </td>
                  <td className="px-3 py-1.5 font-mono">{r.actor}</td>
                  <td className="px-3 py-1.5">{r.action}</td>
                  <td className="px-3 py-1.5">{r.outcome}</td>
                  <td className="px-3 py-1.5 font-mono">{r.target_resource}</td>
                  <td className="px-3 py-1.5 font-mono">
                    {r.trace_id.slice(0, 18)}
                  </td>
                  <td className="px-3 py-1.5">
                    {r.chain_position ?? "—"}
                    {r.backfilled_at ? (
                      <span className="ml-1 text-text-muted">(back-filled)</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
