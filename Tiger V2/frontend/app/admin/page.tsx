"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  LogOut,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { fetchMe, signOut, type ScopeResponse } from "@/lib/auth";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type TenantSummary = {
  id: string;
  slug: string;
  name: string;
  region: string;
  plan: string;
  status: string;
  created_at: string;
};

type AuditLogRow = {
  id: string;
  tenant_id: string;
  user_id: string | null;
  event_type: string;
  capability: string | null;
  result: string;
  signed_hash: string;
  prev_hash: string;
  created_at: string;
};

type PendingActionRow = {
  id: string;
  tenant_id: string;
  user_id: string;
  capability: string;
  status: string;
  expires_at: string;
  confirmed_at: string | null;
  executed_at: string | null;
};

type ChainVerification = {
  tenant_id: string;
  ok: boolean;
  rows_checked: number;
  broken_row_id: string | null;
};

function _maybeBounceTo401(status: number): void {
  if (status !== 401 || typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/sign-in")) return;
  window.location.assign(
    `/sign-in?next=${encodeURIComponent(window.location.pathname)}`,
  );
}

async function adminGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { credentials: "include" });
  if (!res.ok) {
    _maybeBounceTo401(res.status);
    throw new Error(`${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

async function adminPost<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    _maybeBounceTo401(res.status);
    throw new Error(`${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export default function AdminLandingPage() {
  const router = useRouter();
  const [scope, setScope] = useState<ScopeResponse | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditLogRow[] | null>(null);
  const [pending, setPending] = useState<PendingActionRow[] | null>(null);
  const [chain, setChain] = useState<ChainVerification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Initial load.
  useEffect(() => {
    void (async () => {
      setScope(await fetchMe());
      try {
        const list = await adminGet<TenantSummary[]>("/admin/tenants");
        setTenants(list);
        if (list.length > 0) setSelected(list[0].id);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  // Per-tenant detail fetch — declared as a callable so the Refresh button
  // can re-trigger it without going through useEffect. ``resetChain`` is true
  // when the user switched tenants (vs. just clicking Refresh on the same
  // tenant), so a stale verify result for the previous tenant doesn't leak
  // across the switch.
  const loadTenantDetail = async (tenantId: string, resetChain: boolean) => {
    setBusy(true);
    setError(null);
    if (resetChain) setChain(null);
    try {
      const [a, p] = await Promise.all([
        adminGet<AuditLogRow[]>(
          `/admin/tenants/${encodeURIComponent(tenantId)}/audit-logs?limit=50`,
        ),
        adminGet<PendingActionRow[]>(
          `/admin/tenants/${encodeURIComponent(tenantId)}/pending-actions?limit=50`,
        ),
      ]);
      setAudit(a);
      setPending(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!selected) return;
    const tenantId = selected;
    void (async () => {
      await loadTenantDetail(tenantId, true);
    })();
  }, [selected]);

  const onVerifyChain = async () => {
    if (!selected) return;
    const tenantAtStart = selected;
    setBusy(true);
    setError(null);
    try {
      const v = await adminPost<ChainVerification>(
        `/admin/tenants/${encodeURIComponent(tenantAtStart)}/audit-logs/verify`,
      );
      // Discard the result if the user has switched tenants while we were waiting.
      if (tenantAtStart === selected) setChain(v);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onSignOut = async () => {
    await signOut();
    router.replace("/sign-in");
  };

  return (
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-5">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-wide text-text-muted">
              Platform admin
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              Tigeri operations
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              {scope ? (
                <>
                  Signed in as <span className="font-mono text-text-primary">{scope.user_email}</span>{" "}
                  ({scope.role}) · tenant{" "}
                  <span className="font-mono text-text-primary">{scope.tenant_slug}</span>
                </>
              ) : (
                "Loading scope…"
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/admin/users"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5"
            >
              User credentials <ChevronRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/admin/integrations"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5"
            >
              OAuth credentials <ChevronRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/admin/feedback"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5"
            >
              Chat feedback <ChevronRight className="h-3.5 w-3.5" />
            </Link>
            <button
              onClick={() => void onSignOut()}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:text-text-danger"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </header>

        {error ? (
          <div className="mt-5 rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
            {error}
          </div>
        ) : null}

        <section className="mt-6 grid gap-4 lg:grid-cols-[280px_1fr]">
          {/* Tenants column */}
          <aside className="rounded-md border border-border bg-surface p-3">
            <h2 className="mb-3 px-1 font-mono text-[11px] uppercase tracking-wide text-text-muted">
              Tenants ({tenants?.length ?? "—"})
            </h2>
            {!tenants ? (
              <div className="px-1 text-xs text-text-secondary">Loading…</div>
            ) : tenants.length === 0 ? (
              <div className="px-1 text-xs text-text-secondary">No tenants yet.</div>
            ) : (
              <ul className="space-y-1">
                {tenants.map((t) => (
                  <li key={t.id}>
                    <button
                      onClick={() => setSelected(t.id)}
                      className={`w-full rounded-md px-2 py-2 text-left text-sm transition-colors ${
                        selected === t.id
                          ? "bg-navy text-white"
                          : "text-text-primary hover:bg-background-5"
                      }`}
                    >
                      <div className="font-medium">{t.name}</div>
                      <div
                        className={`font-mono text-[11px] ${
                          selected === t.id ? "text-white/70" : "text-text-muted"
                        }`}
                      >
                        {t.slug} · {t.region} · {t.plan} · {t.status}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Detail column */}
          <div className="space-y-4">
            {/* Audit chain card */}
            <section className="rounded-md border border-border bg-surface p-5">
              <header className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="font-mono text-[11px] uppercase tracking-wide text-text-muted">
                    Audit log (latest 50)
                  </h2>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    HMAC-SHA256 hash chain. Verify recomputes every row in
                    order — a single tampered row breaks the chain from there.
                  </p>
                </div>
                <button
                  onClick={() => void onVerifyChain()}
                  disabled={!selected || busy}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-background-5 disabled:opacity-50"
                >
                  <ShieldCheck className="h-3.5 w-3.5" /> Verify chain
                </button>
              </header>

              {chain ? (
                <div
                  className={`mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${
                    chain.ok
                      ? "border-success/40 bg-surface-blue text-success"
                      : "border-danger bg-background text-text-danger"
                  }`}
                >
                  {chain.ok ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  <span>
                    {chain.ok
                      ? `Chain valid · ${chain.rows_checked} rows checked.`
                      : `Chain BROKEN at ${chain.broken_row_id} · ${chain.rows_checked} rows checked before mismatch.`}
                  </span>
                </div>
              ) : null}

              {!audit ? (
                <p className="mt-3 text-xs text-text-secondary">Loading…</p>
              ) : audit.length === 0 ? (
                <p className="mt-3 text-xs text-text-secondary">
                  No audit log entries yet for this tenant.
                </p>
              ) : (
                <div className="mt-3 overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-surface-blue text-text-secondary">
                      <tr className="text-left">
                        <th className="px-3 py-2">Time</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Capability</th>
                        <th className="px-3 py-2">Result</th>
                        <th className="px-3 py-2">User</th>
                        <th className="px-3 py-2">Hash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {audit.map((r) => (
                        <tr key={r.id} className="border-t border-border-5">
                          <td className="px-3 py-1.5 font-mono">
                            {r.created_at.slice(0, 19)}
                          </td>
                          <td className="px-3 py-1.5">{r.event_type}</td>
                          <td className="px-3 py-1.5 font-mono">
                            {r.capability ?? "—"}
                          </td>
                          <td className="px-3 py-1.5">{r.result}</td>
                          <td className="px-3 py-1.5 font-mono">
                            {r.user_id ?? "—"}
                          </td>
                          <td
                            className="px-3 py-1.5 font-mono text-text-muted"
                            title={`signed: ${r.signed_hash}\nprev: ${r.prev_hash}`}
                          >
                            {r.signed_hash.slice(0, 14)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Pending actions card */}
            <section className="rounded-md border border-border bg-surface p-5">
              <header className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="font-mono text-[11px] uppercase tracking-wide text-text-muted">
                    Pending actions (latest 50)
                  </h2>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    Write actions proposed by the AI. Pending → Confirmed →
                    Executed (or Cancelled / Expired / Failed).
                  </p>
                </div>
                <button
                  onClick={() => selected && void loadTenantDetail(selected, false)}
                  disabled={!selected || busy}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-background-5 disabled:opacity-50"
                >
                  <RefreshCw className={"h-3.5 w-3.5 " + (busy ? "animate-spin" : "")} />
                  Refresh
                </button>
              </header>
              {!pending ? (
                <p className="mt-3 text-xs text-text-secondary">Loading…</p>
              ) : pending.length === 0 ? (
                <p className="mt-3 text-xs text-text-secondary">
                  No pending actions yet for this tenant.
                </p>
              ) : (
                <div className="mt-3 overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-surface-blue text-text-secondary">
                      <tr className="text-left">
                        <th className="px-3 py-2">Capability</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">User</th>
                        <th className="px-3 py-2">Expires</th>
                        <th className="px-3 py-2">Confirmed</th>
                        <th className="px-3 py-2">Executed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pending.map((p) => (
                        <tr key={p.id} className="border-t border-border-5">
                          <td className="px-3 py-1.5 font-mono">{p.capability}</td>
                          <td className="px-3 py-1.5">{p.status}</td>
                          <td className="px-3 py-1.5 font-mono">{p.user_id}</td>
                          <td className="px-3 py-1.5 font-mono">
                            {p.expires_at.slice(0, 19)}
                          </td>
                          <td className="px-3 py-1.5 font-mono">
                            {p.confirmed_at ? p.confirmed_at.slice(0, 19) : "—"}
                          </td>
                          <td className="px-3 py-1.5 font-mono">
                            {p.executed_at ? p.executed_at.slice(0, 19) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </section>
      </main>
      <GlobalFooter />
    </div>
  );
}
