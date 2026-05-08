"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentCard, AuditRecord } from "@/lib/type";

export default function AgentDetailWrapper() {
  return (
    <Suspense fallback={<div className="text-sm text-text-secondary">Loading…</div>}>
      <AgentDetailPage />
    </Suspense>
  );
}

function AgentDetailPage() {
  const search = useSearchParams();
  const agentId = search?.get("id") ?? "";

  const [card, setCard] = useState<AgentCard | null>(null);
  const [audit, setAudit] = useState<AuditRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) return;
    Promise.all([
      api.getAgentCard(agentId),
      api.listAudit({ actor: `${agentId}:api`, limit: 50 }),
    ])
      .then(([c, a]) => {
        setCard(c);
        setAudit(a);
      })
      .catch((e) => setError((e as Error).message));
  }, [agentId]);

  if (error)
    return (
      <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
        {error}
      </div>
    );
  if (!card) return <div className="text-sm text-text-secondary">Loading…</div>;

  return (
    <div className="space-y-6">
      <Link
        href="/client-dashboard/home"
        className="inline-flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to catalog
      </Link>

      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
          #{card.priority} · {card.phase}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{card.name}</h1>
        <p className="text-sm text-text-secondary max-w-2xl">{card.function}</p>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
            Card
          </h2>
          <dl className="mt-3 space-y-2 text-sm">
            <Field label="Status" value={card.status} />
            <Field label="Trust tier" value={card.default_trust_tier} />
            <Field label="Surfaces" value={card.delivery_surfaces.join(", ")} />
            <Field label="ROI baseline" value={card.roi_baseline} />
            <Field label="Version" value={card.version} />
          </dl>
        </div>
        <div className="rounded-md border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
            Required integrations
          </h2>
          <ul className="mt-3 space-y-2 text-sm">
            {card.required_integrations.map((i) => (
              <li
                key={i.category}
                className="flex items-center justify-between border-b border-border-5 pb-2 last:border-b-0"
              >
                <span>{i.category}</span>
                <span className="tag-info">{i.access_pattern}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="rounded-md border border-border bg-surface p-4">
        <header className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
            Recent audit (50)
          </h2>
          <Link href="/audit" className="text-xs text-navy hover:underline">
            Full log
          </Link>
        </header>
        {!audit ? (
          <p className="mt-3 text-sm text-text-secondary">Loading audit…</p>
        ) : audit.length === 0 ? (
          <p className="mt-3 text-sm text-text-secondary">
            No audit records yet for this agent.
          </p>
        ) : (
          <table className="mt-3 w-full text-xs">
            <thead className="text-text-muted">
              <tr className="text-left">
                <th className="py-1">Timestamp</th>
                <th className="py-1">Action</th>
                <th className="py-1">Outcome</th>
                <th className="py-1">Target</th>
                <th className="py-1">Trace</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((r) => (
                <tr key={r.id} className="border-t border-border-5">
                  <td className="py-1 font-mono">{r.timestamp_utc.slice(0, 19)}</td>
                  <td className="py-1">{r.action}</td>
                  <td className="py-1">{r.outcome}</td>
                  <td className="py-1 font-mono">{r.target_resource}</td>
                  <td className="py-1 font-mono">{r.trace_id.slice(0, 18)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border-5 pb-2 last:border-b-0">
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-text-primary">{value}</dd>
    </div>
  );
}
