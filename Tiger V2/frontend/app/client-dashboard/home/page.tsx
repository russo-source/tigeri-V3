"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ChevronRight,
  Activity,
  CheckCircle2,
  Circle,
  ExternalLink,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentCard, AuditRecord } from "@/lib/type";

type Phase = "Phase 1 — Core MVP" | "Phase 2 — Next Build" | "Phase 3 — Enterprise";
const PHASES: Phase[] = [
  "Phase 1 — Core MVP",
  "Phase 2 — Next Build",
  "Phase 3 — Enterprise",
];

const TIER_TAG: Record<string, string> = {
  OBSERVER: "tag-info",
  RECOMMENDER: "tag-warning",
  ACTOR_GATED: "tag-active",
  ACTOR_ELEVATED: "tag-error",
};

type IntegrationsHealth = Awaited<ReturnType<typeof api.integrationsHealth>>;

export default function HomePage() {
  const [cards, setCards] = useState<AgentCard[] | null>(null);
  const [audit, setAudit] = useState<AuditRecord[] | null>(null);
  const [health, setHealth] = useState<IntegrationsHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAgents()
      .then(setCards)
      .catch((e) => setError((e as Error).message));
    api
      .listAudit({ limit: 5 })
      .then(setAudit)
      .catch(() => setAudit([])); // soft-fail; widget hides on error
    api
      .integrationsHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  if (error)
    return (
      <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
        {error}
      </div>
    );

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Your Tigeri workspace at a glance — recent activity, pilot
          checklist, and the agent catalog.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        <ActivityCard rows={audit} />
        <OnboardingCard health={health} />
      </section>

      {!cards ? (
        <div className="text-sm text-text-secondary">Loading agent catalog…</div>
      ) : (
        <AgentCatalog cards={cards} />
      )}
    </div>
  );
}

function ActivityCard({ rows }: { rows: AuditRecord[] | null }) {
  return (
    <article className="rounded-md border border-border bg-surface p-5">
      <header className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-text-muted" />
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
          Recent activity
        </h2>
      </header>
      {rows === null ? (
        <p className="mt-3 text-xs text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-3 text-xs text-text-secondary">
          Nothing yet. Run an agent — your audit chain shows up here.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-border-5 text-sm">
          {rows.slice(0, 5).map((r) => (
            <li key={r.id} className="flex items-start justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate font-medium text-text-primary">
                  {r.action}
                </p>
                <p className="truncate font-mono text-[11px] text-text-muted">
                  {r.actor} · {r.target_resource} · {r.outcome}
                </p>
              </div>
              <span className="shrink-0 font-mono text-[11px] text-text-muted">
                {r.timestamp_utc.slice(11, 16)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        <Link
          href="/audit"
          className="inline-flex items-center gap-1 text-xs font-medium text-navy hover:underline"
        >
          See all <ChevronRight className="h-3 w-3" />
        </Link>
      </div>
    </article>
  );
}

function OnboardingCard({ health }: { health: IntegrationsHealth | null }) {
  // Each row resolves to ✅ done / ⭕ pending. ``done`` is computed from
  // /v1/integrations/health for connection-style steps; the rest are
  // suggestions until we wire per-tenant onboarding state into the DB.
  const checklist = useMemo(() => {
    const connected = (provider: string) =>
      !!health?.providers.find((p) => p.provider === provider && p.connected);

    return [
      {
        label: "Connect Google Workspace",
        done: connected("google"),
        href: "/integrations",
      },
      {
        label: "Connect Xero (or QuickBooks)",
        done: connected("xero") || connected("quickbooks"),
        href: "/integrations",
      },
      {
        label: "Connect Telegram bot",
        done: connected("telegram"),
        href: "/integrations",
      },
      {
        label: "Run your first invoice",
        done: false, // TODO: wire to first invoice_agent run in audit_logs
        href: "/agents/invoice",
      },
      {
        label: "Invite a teammate",
        done: false, // TODO: wire to user count > 1 for this tenant
        href: "/admin/users",
      },
    ];
  }, [health]);

  const completed = checklist.filter((c) => c.done).length;

  return (
    <article className="rounded-md border border-border bg-surface p-5">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
          Pilot checklist
        </h2>
        <span className="font-mono text-[11px] text-text-muted">
          {completed} / {checklist.length}
        </span>
      </header>
      <ul className="mt-3 space-y-2 text-sm">
        {checklist.map((row) => (
          <li key={row.label}>
            <Link
              href={row.href}
              className="flex items-center gap-2 rounded-md px-1.5 py-1 transition-colors hover:bg-background-5"
            >
              {row.done ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <Circle className="h-4 w-4 text-text-muted" />
              )}
              <span
                className={
                  row.done
                    ? "text-text-secondary line-through"
                    : "text-text-primary"
                }
              >
                {row.label}
              </span>
              <ExternalLink className="ml-auto h-3 w-3 text-text-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </article>
  );
}

function AgentCatalog({ cards }: { cards: AgentCard[] }) {
  const grouped = PHASES.map((phase) => ({
    phase,
    items: cards.filter((c) => c.phase === phase),
  }));
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold tracking-tight">Agent catalog</h2>
        <p className="mt-0.5 text-xs text-text-secondary">
          {cards.length} agents loaded from <code>/agents</code>. Build order
          follows the catalog priority field.
        </p>
      </header>

      {grouped.map(
        (section) =>
          section.items.length > 0 && (
            <section key={section.phase} className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
                {section.phase}
              </h3>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {section.items.map((c) => (
                  <motion.div
                    key={c.agent_id}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <Link
                      href={`/client-dashboard/home/agent?id=${c.agent_id}`}
                      className="group block rounded-md border border-border bg-surface p-4 transition-colors hover:border-navy"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-xs font-medium text-text-muted">
                            #{c.priority} · {c.status}
                          </p>
                          <h3 className="mt-1 text-base font-semibold">
                            {c.name}
                          </h3>
                        </div>
                        <ChevronRight className="h-4 w-4 text-text-muted transition-transform group-hover:translate-x-0.5" />
                      </div>
                      <p className="mt-2 text-sm text-text-secondary">
                        {c.function}
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                        <span className={TIER_TAG[c.default_trust_tier] ?? "tag-info"}>
                          {c.default_trust_tier}
                        </span>
                        {c.delivery_surfaces.includes("mobile") && (
                          <span className="tag-info">mobile</span>
                        )}
                        <span className="tag-success">{c.roi_baseline}</span>
                      </div>
                    </Link>
                  </motion.div>
                ))}
              </div>
            </section>
          ),
      )}
    </div>
  );
}
