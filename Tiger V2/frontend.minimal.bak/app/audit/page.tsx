"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AuditRecord } from "@/lib/types";

export default function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [traceFilter, setTraceFilter] = useState("");

  async function refresh() {
    setError(null);
    try {
      const rows = await api.listAudit({
        trace_id: traceFilter || undefined,
        limit: 200,
      });
      setRecords(rows);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold text-zinc-900">Audit log</h1>
        <div className="flex gap-2">
          <input
            value={traceFilter}
            onChange={(e) => setTraceFilter(e.target.value)}
            placeholder="filter by trace_id"
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => void refresh()}
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white"
          >
            Refresh
          </button>
        </div>
      </div>
      <p className="text-xs text-zinc-500">
        Local append-only buffer. Once the Compliance &amp; Audit Agent (Priority
        12) is live, rows will populate <code>chain_position</code> and{" "}
        <code>backfilled_at</code>.
      </p>
      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}
      {!records && <div className="text-sm text-zinc-500">Loading…</div>}
      {records && records.length === 0 && (
        <div className="text-sm text-zinc-500">No records yet.</div>
      )}
      {records && records.length > 0 && (
        <table className="w-full overflow-hidden rounded-lg border border-zinc-200 bg-white text-xs">
          <thead className="bg-zinc-50 text-left text-[11px] uppercase text-zinc-500">
            <tr>
              <th className="px-3 py-2">Timestamp (UTC)</th>
              <th className="px-3 py-2">Actor</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Outcome</th>
              <th className="px-3 py-2">Target</th>
              <th className="px-3 py-2">Trace id</th>
              <th className="px-3 py-2">Chain</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} className="border-t border-zinc-200">
                <td className="px-3 py-1.5 font-mono">{r.timestamp_utc}</td>
                <td className="px-3 py-1.5 font-mono">{r.actor}</td>
                <td className="px-3 py-1.5">{r.action}</td>
                <td className="px-3 py-1.5">{r.outcome}</td>
                <td className="px-3 py-1.5 font-mono">{r.target_resource}</td>
                <td className="px-3 py-1.5 font-mono">{r.trace_id}</td>
                <td className="px-3 py-1.5">
                  {r.chain_position ?? "—"}
                  {r.backfilled_at && (
                    <span className="ml-1 text-zinc-400">
                      (back-filled)
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
