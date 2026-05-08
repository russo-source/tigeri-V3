"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, RefreshCw, X } from "lucide-react";
import { api, getTenantId } from "@/lib/api";

type ProviderHealth = {
  provider: string;
  connected: boolean;
  healthy: boolean | null;
  latency_ms: number | null;
  error: string | null;
  meta: Record<string, string>;
};

type Health = {
  summary: { connected: number; healthy: number; failing: number; total: number };
  providers: ProviderHealth[];
};

const FRIENDLY: Record<string, string> = {
  xero: "Xero",
  quickbooks: "QuickBooks",
  google: "Google Workspace",
  microsoft: "Microsoft 365",
  paypal: "PayPal",
  telegram: "Telegram",
};

function explain(p: ProviderHealth): string {
  if (p.error) {
    if (p.error.toLowerCase().includes("refresh failed")) {
      return "Token expired or revoked. Reconnect to continue.";
    }
    if (p.error.includes("HTTP 401")) return "Authorisation rejected. Reconnect.";
    if (p.error.includes("HTTP 403")) return "Permissions denied for this scope.";
    return p.error.slice(0, 140);
  }
  if (p.connected && p.healthy) return `Healthy${p.latency_ms ? ` · ${p.latency_ms} ms` : ""}.`;
  return "";
}

export default function IntegrationsBanner() {
  const [health, setHealth] = useState<Health | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchHealth = async () => {
    if (!getTenantId()) return;
    setRefreshing(true);
    try {
      const h = await api.integrationsHealth();
      setHealth(h);
    } catch {
      /* swallow — banner is best-effort */
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void fetchHealth();
  }, []);

  if (dismissed || !health) return null;

  const failing = health.providers.filter((p) => p.healthy === false);
  const ok = health.summary.healthy;
  const connected = health.summary.connected;
  const sandboxCount = health.providers.filter(
    (p) => p.connected && p.meta?.mode === "sandbox",
  ).length;

  if (connected === 0) return null;

  if (failing.length === 0) {
    return (
      <div className="border-b border-border bg-surface px-4 py-2 text-xs text-text-secondary">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <span className="inline-flex flex-wrap items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-success" />
            <span className="text-text-primary">
              {ok}/{connected} integration{connected === 1 ? "" : "s"} healthy
              {sandboxCount > 0 ? ` (${sandboxCount} demo)` : ""}.
            </span>
            {health.providers
              .filter((p) => p.connected && p.healthy)
              .map((p) => {
                const isDemo = p.meta?.mode === "sandbox";
                return (
                  <span
                    key={p.provider}
                    className={
                      "rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide " +
                      (isDemo
                        ? "border-warning/40 text-text-warning"
                        : "border-success/40 text-success")
                    }
                  >
                    {FRIENDLY[p.provider] ?? p.provider}
                    {isDemo ? " · demo" : ""}
                  </span>
                );
              })}
          </span>
          <button
            aria-label="Dismiss"
            onClick={() => setDismissed(true)}
            className="text-text-muted hover:text-text-primary"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-danger bg-background px-4 py-3 text-xs text-text-danger">
      <div className="mx-auto flex max-w-6xl items-start justify-between gap-4">
        <div className="min-w-0 space-y-1.5">
          <div className="inline-flex items-center gap-2 font-medium">
            <AlertTriangle className="h-3.5 w-3.5" />
            {failing.length} integration{failing.length === 1 ? "" : "s"} need attention.
          </div>
          <ul className="space-y-1">
            {failing.map((p) => (
              <li key={p.provider} className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-text-primary">
                  {FRIENDLY[p.provider] ?? p.provider}:
                </span>
                <span className="text-text-secondary">{explain(p)}</span>
                <a
                  href={api.connectProviderUrl(p.provider)}
                  className="ml-auto inline-flex items-center gap-1 rounded-sm bg-navy px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-white transition-colors hover:bg-navy-dark"
                >
                  Reconnect
                </a>
              </li>
            ))}
          </ul>
          <div className="text-[11px] text-text-secondary">
            <Link href="/integrations" className="text-navy hover:underline">
              Manage all integrations →
            </Link>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="Re-check"
            onClick={() => void fetchHealth()}
            disabled={refreshing}
            className="rounded-sm border border-border bg-surface px-2 py-1 text-[11px] font-medium text-text-primary transition-colors hover:bg-background-5 disabled:opacity-50"
          >
            <RefreshCw className={"inline h-3 w-3 " + (refreshing ? "animate-spin" : "")} />
            <span className="ml-1">Re-check</span>
          </button>
          <button
            aria-label="Dismiss"
            onClick={() => setDismissed(true)}
            className="text-text-danger/70 hover:text-text-danger"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
