"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  ExternalLink,
  Key,
  Plug,
  Send,
  Unplug,
} from "lucide-react";
import { api, getTenantId } from "@/lib/api";
import { fetchMe, isAdmin, type ScopeResponse } from "@/lib/auth";

type ProviderConfig = {
  provider: string;
  configured: boolean;
  source: "tenant" | "platform";
  client_id: string;
  custom_redirect_uri: string | null;
  custom_scopes: string[] | null;
};

type ProviderStatus = {
  connected: boolean;
  expires_at?: string;
  is_expired?: boolean;
  meta?: Record<string, string>;
};

type StatusMap = Record<string, ProviderStatus>;

const OAUTH_PROVIDERS: {
  id: string;
  name: string;
  description: string;
}[] = [
  {
    id: "xero",
    name: "Xero",
    description: "Post Invoice Agent results to your Xero org as draft invoices.",
  },
  {
    id: "quickbooks",
    name: "QuickBooks Online",
    description: "Post Invoice Agent results to QuickBooks Online (sandbox).",
  },
  {
    id: "google",
    name: "Google Workspace",
    description: "Calendar conflict checks for Booking Agent + Gmail outbound for Admin Agent.",
  },
  {
    id: "microsoft",
    name: "Microsoft 365",
    description: "Outlook sendMail + Teams + Graph identity.",
  },
  {
    id: "paypal",
    name: "PayPal",
    description: "Identity round-trip + payment intents (sandbox).",
  },
];

export default function IntegrationsPageWrapper() {
  return (
    <Suspense fallback={<div className="text-sm text-text-secondary">Loading…</div>}>
      <IntegrationsPage />
    </Suspense>
  );
}

type Health = Awaited<ReturnType<typeof api.integrationsHealth>>;

function IntegrationsPage() {
  const search = useSearchParams();
  const [statuses, setStatuses] = useState<StatusMap | null>(null);
  const [configs, setConfigs] = useState<Record<string, ProviderConfig>>({});
  const [scope, setScope] = useState<ScopeResponse | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const canAdmin = isAdmin(scope);

  async function refreshConfigs() {
    const out: Record<string, ProviderConfig> = {};
    for (const p of OAUTH_PROVIDERS) {
      try {
        out[p.id] = await api.getProviderConfig(p.id);
      } catch {
        // Skip — config endpoint may be unavailable on older deploys.
      }
    }
    setConfigs(out);
  }

  const justConnected = search?.get("integration");
  const status = search?.get("status");
  const reason = search?.get("reason");

  async function refresh() {
    setError(null);
    try {
      const s = await api.integrationsStatus();
      setStatuses(s);
    } catch (e) {
      setError((e as Error).message);
    }
    // Health is best-effort — its endpoint is slower (calls each provider)
    // and we don't want a single provider's outage to block the page.
    try {
      const h = await api.integrationsHealth();
      setHealth(h);
    } catch {
      setHealth(null);
    }
  }

  useEffect(() => {
    void refresh();
    void refreshConfigs();
    void (async () => setScope(await fetchMe()))();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function disconnect(provider: string) {
    setBusy(provider);
    try {
      await api.disconnectProvider(provider);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function demoConnect(provider: string) {
    setBusy(provider);
    try {
      await api.connectDemo(provider);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const tenantId = getTenantId();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Connect a provider to make the agents act on real systems. Tokens are
          encrypted at rest and refreshed automatically.
        </p>
      </header>

      {scope && !canAdmin ? (
        <div className="rounded-md border border-warning/40 bg-surface p-3 text-xs text-text-secondary">
          <span className="font-mono uppercase tracking-wide text-text-warning">
            Read-only view
          </span>{" "}
          — your role is{" "}
          <span className="font-mono text-text-primary">{scope.role}</span>.
          Connecting, disconnecting, and configuring OAuth apps requires the{" "}
          <span className="font-mono text-text-primary">owner</span> or{" "}
          <span className="font-mono text-text-primary">admin</span> role. Ask
          a workspace admin to make changes.
        </div>
      ) : null}

      {justConnected && status === "connected" ? (
        <div className="rounded-md border border-success bg-background p-3 text-sm text-success">
          <CheckCircle2 className="mr-2 inline h-4 w-4" /> {justConnected} connected.
        </div>
      ) : null}
      {justConnected && status === "failed" ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
          {justConnected} connection failed: {reason ?? "unknown error"}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">{error}</div>
      ) : null}

      {health ? (
        <section className="rounded-md border border-border bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
              Live health
            </h2>
            <div className="flex items-center gap-3 text-xs">
              <span className="font-mono">
                {health.summary.connected}/{health.summary.total} connected
              </span>
              <span className="font-mono text-success">
                {health.summary.healthy} healthy
              </span>
              {health.summary.failing > 0 ? (
                <span className="font-mono text-text-danger">
                  {health.summary.failing} failing
                </span>
              ) : null}
            </div>
          </div>
          <ul className="mt-3 grid gap-1.5 text-xs sm:grid-cols-2">
            {health.providers.map((p) => {
              const dotClass =
                p.healthy === true
                  ? "bg-success"
                  : p.healthy === false
                    ? "bg-danger"
                    : "bg-text-muted";
              const label =
                p.healthy === true
                  ? "healthy"
                  : p.healthy === false
                    ? "failing"
                    : p.connected
                      ? "unknown"
                      : "not connected";
              return (
                <li
                  key={p.provider}
                  className="flex items-center gap-2 font-mono"
                >
                  <span className={`h-2 w-2 rounded-full ${dotClass}`} />
                  <span className="text-text-primary">{p.provider}</span>
                  <span className="text-text-muted">— {label}</span>
                  {typeof p.latency_ms === "number" ? (
                    <span className="ml-auto text-text-muted">
                      {p.latency_ms} ms
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
          OAuth providers
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          {OAUTH_PROVIDERS.map((p) => {
            const s = statuses?.[p.id];
            const connected = s?.connected ?? false;
            const sandbox = s?.meta?.mode === "sandbox";
            const badgeClass = sandbox
              ? "tag-warning"
              : connected
                ? "tag-success"
                : "tag-info";
            const badgeLabel = sandbox
              ? "Connected (demo)"
              : connected
                ? "Connected"
                : "Available";
            return (
              <div
                key={p.id}
                className="rounded-md border border-border bg-surface p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold">{p.name}</h3>
                    <p className="mt-1 text-sm text-text-secondary">{p.description}</p>
                  </div>
                  <span className={badgeClass}>{badgeLabel}</span>
                </div>
                {connected && s?.meta ? (
                  <dl className="mt-3 space-y-1 text-xs text-text-muted">
                    {Object.entries(s.meta).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-2">
                        <dt>{k}</dt>
                        <dd className="font-mono text-text-primary">{v}</dd>
                      </div>
                    ))}
                    {s.expires_at && !sandbox ? (
                      <div className="flex justify-between gap-2">
                        <dt>access expires</dt>
                        <dd className="font-mono">{s.expires_at.slice(0, 19)}</dd>
                      </div>
                    ) : null}
                  </dl>
                ) : null}
                {/* App-source indicator: tenant's own client_id vs Tigeri default */}
                {configs[p.id] ? (
                  <p className="mt-3 font-mono text-[10px] uppercase tracking-wide text-text-muted">
                    OAuth app:{" "}
                    {configs[p.id].source === "tenant" ? (
                      <span className="text-text-primary">
                        Your registration ({configs[p.id].client_id.slice(0, 16)}…)
                      </span>
                    ) : (
                      "Tigeri default"
                    )}
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {!connected ? (
                    canAdmin ? (
                      <>
                        <a
                          href={api.connectProviderUrl(p.id)}
                          className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark"
                        >
                          <Plug className="h-3.5 w-3.5" /> Connect {p.name}
                          <ExternalLink className="h-3 w-3 opacity-70" />
                        </a>
                        <button
                          onClick={() => void demoConnect(p.id)}
                          disabled={busy === p.id}
                          title="Skip OAuth — mark as connected for demo purposes only"
                          className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-background-5 hover:text-text-primary disabled:opacity-50"
                        >
                          Demo connect
                        </button>
                      </>
                    ) : (
                      <span className="font-mono text-[10px] uppercase tracking-wide text-text-muted">
                        Admin role required
                      </span>
                    )
                  ) : canAdmin ? (
                    <button
                      onClick={() => void disconnect(p.id)}
                      disabled={busy === p.id}
                      className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-text-danger transition-colors hover:border-danger hover:bg-background-5 disabled:opacity-50"
                    >
                      <Unplug className="h-3.5 w-3.5" /> Disconnect
                    </button>
                  ) : null}
                  {canAdmin ? (
                    <Link
                      href="/admin/integrations"
                      className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-background-5 hover:text-text-primary"
                      title="Bring Your Own App: enter OAuth credentials in the admin page"
                    >
                      <Key className="h-3.5 w-3.5" /> Manage app credentials
                    </Link>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* BYOA configure modal moved to /admin/integrations — admins are routed
          there via the "Manage app credentials" link on each provider card. */}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
          Messaging
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-md border border-border bg-surface p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">Telegram</h3>
                <p className="mt-1 text-sm text-text-secondary">
                  Admin Agent delivers comms to your Telegram chat. Generate a
                  one-time link code below, open the bot, and send{" "}
                  <code className="rounded bg-background-5 px-1 py-0.5 text-xs">/connect &lt;CODE&gt;</code>.
                  Codes expire in 5 minutes and die on first use.
                </p>
              </div>
              <span
                className={
                  statuses?.telegram?.connected ? "tag-success" : "tag-info"
                }
              >
                {statuses?.telegram?.connected ? "Linked" : "Available"}
              </span>
            </div>
            {statuses?.telegram?.meta ? (
              <dl className="mt-3 space-y-1 text-xs text-text-muted">
                {Object.entries(statuses.telegram.meta).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <dt>{k}</dt>
                    <dd className="font-mono text-text-primary">{v}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <TelegramActions
              connected={statuses?.telegram?.connected ?? false}
              canAdmin={canAdmin}
              onUnlink={() => void disconnect("telegram")}
            />
          </div>

          <WhatsAppCard
            connected={statuses?.whatsapp?.connected ?? false}
            recipient={statuses?.whatsapp?.meta?.recipient_msisdn}
            canAdmin={canAdmin}
            onChange={() => void refresh()}
          />
        </div>
      </section>
    </div>
  );
}

function TelegramActions({
  connected,
  canAdmin,
  onUnlink,
}: {
  connected: boolean;
  canAdmin: boolean;
  onUnlink: () => void;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onGenerate = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.telegramLinkCode();
      setCode(res.code);
      setExpiresAt(res.expires_at);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center gap-2">
        <a
          href="https://t.me/Tigerimario_bot"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-elevated px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5"
        >
          <Send className="h-3.5 w-3.5" /> Open @Tigerimario_bot
          <ExternalLink className="h-3 w-3 opacity-70" />
        </a>
        {canAdmin ? (
          <button
            onClick={() => void onGenerate()}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
          >
            <Key className="h-3.5 w-3.5" />
            {busy ? "Generating…" : "Generate link code"}
          </button>
        ) : null}
        {connected && canAdmin ? (
          <button
            onClick={onUnlink}
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-text-danger transition-colors hover:border-danger hover:bg-background-5"
          >
            <Unplug className="h-3.5 w-3.5" /> Unlink
          </button>
        ) : null}
      </div>
      {code ? (
        <div className="rounded-md border border-success/40 bg-surface-blue p-3 text-xs">
          <p className="font-mono uppercase tracking-wide text-text-muted">
            One-time link code
          </p>
          <p className="mt-1 font-mono text-lg tracking-widest text-text-primary">
            {code}
          </p>
          <p className="mt-2 text-text-secondary">
            Send <code className="rounded bg-surface-elevated px-1">/connect {code}</code>{" "}
            to @Tigerimario_bot from the Telegram chat you want linked.
            {expiresAt ? ` Expires ${expiresAt.slice(11, 19)} UTC.` : ""}
          </p>
        </div>
      ) : null}
      {err ? <p className="text-xs text-text-danger">{err}</p> : null}
    </div>
  );
}

function WhatsAppCard({
  connected,
  recipient,
  canAdmin,
  onChange,
}: {
  connected: boolean;
  recipient?: string;
  canAdmin: boolean;
  onChange: () => void;
}) {
  const [phone, setPhone] = useState(recipient ?? "");
  const [busy, setBusy] = useState<"opt" | "test" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function optIn() {
    setBusy("opt");
    setErr(null);
    setMsg(null);
    try {
      const out = await api.whatsappOptin(phone);
      setMsg(`Opted in ${out.recipient_msisdn}.`);
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function sendTest() {
    setBusy("test");
    setErr(null);
    setMsg(null);
    try {
      await api.whatsappTestSend("Hello from Tigeri.ai · Admin Agent test message");
      setMsg("Sent. Check WhatsApp.");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rounded-md border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">WhatsApp Business</h3>
          <p className="mt-1 text-sm text-text-secondary">
            Admin Agent comms over WhatsApp via 360dialog. No OAuth — opt in
            with the recipient&apos;s phone number (E.164 digits, no &lsquo;+&rsquo;).
          </p>
        </div>
        <span className={connected ? "tag-success" : "tag-info"}>
          {connected ? "Linked" : "Available"}
        </span>
      </div>
      {connected && recipient ? (
        <p className="mt-3 text-xs text-text-muted">
          Sending to: <span className="font-mono text-text-primary">{recipient}</span>
        </p>
      ) : null}

      {canAdmin ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="9995322303"
            inputMode="numeric"
            className="w-44 rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono text-text-primary outline-none transition-colors focus:border-navy"
          />
          <button
            onClick={() => void optIn()}
            disabled={busy !== null || phone.length < 8}
            className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
          >
            {busy === "opt" ? "Saving…" : connected ? "Update phone" : "Opt in"}
          </button>
          {connected ? (
            <button
              onClick={() => void sendTest()}
              disabled={busy !== null}
              className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5 disabled:opacity-50"
            >
              {busy === "test" ? "Sending…" : "Send test"}
            </button>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 font-mono text-[10px] uppercase tracking-wide text-text-muted">
          Admin role required to manage WhatsApp recipient
        </p>
      )}
      {msg ? <p className="mt-2 text-xs text-success">{msg}</p> : null}
      {err ? <p className="mt-2 text-xs text-text-danger">{err}</p> : null}
    </div>
  );
}

// ConfigureAppModal lives at /admin/integrations now; this page no longer
// renders it. See frontend/app/admin/integrations/page.tsx.

