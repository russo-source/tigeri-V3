"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChevronLeft,
  Key,
  LogOut,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { api } from "@/lib/api";
import { fetchMe, signOut, type ScopeResponse } from "@/lib/auth";

type ProviderConfig = {
  provider: string;
  configured: boolean;
  source: "tenant" | "platform";
  client_id: string;
  custom_redirect_uri: string | null;
  custom_scopes: string[] | null;
};

/** Turn FastAPI's raw HTTPException details into something a human can act on.
 * The most common one users hit is the role gate when they're signed in as a
 * member but loaded the admin page from a stale tab. */
function _humaniseSaveError(raw: string): string {
  const lower = raw.toLowerCase();
  if (lower.includes("requires role")) {
    return (
      "Your session is no longer signed in as an admin. Sign out and back " +
      "in with an owner / admin account, then retry. (This usually happens " +
      "if a member-account sign-in replaced the cookie in another tab.)"
    );
  }
  if (lower.includes("password_change_required")) {
    return (
      "You need to set a permanent password before saving BYOA credentials. " +
      "Go to /change-password and finish the password change flow first."
    );
  }
  if (lower.includes("not authenticated") || lower.includes("401")) {
    return "Your session expired. Sign in again and retry.";
  }
  return raw;
}

const OAUTH_PROVIDERS: {
  id: string;
  name: string;
  description: string;
  docsLink: string;
}[] = [
  {
    id: "xero",
    name: "Xero",
    description:
      "Accounting · Posts Invoice Agent results as draft invoices to your Xero org.",
    docsLink: "https://developer.xero.com/app/manage",
  },
  {
    id: "quickbooks",
    name: "QuickBooks Online",
    description: "Accounting · Posts invoices to QuickBooks (sandbox or production).",
    docsLink: "https://developer.intuit.com/app/developer/myapps",
  },
  {
    id: "google",
    name: "Google Workspace",
    description: "Calendar conflict checks (Booking) + Gmail outbound (Admin).",
    docsLink: "https://console.cloud.google.com/apis/credentials",
  },
  {
    id: "microsoft",
    name: "Microsoft 365",
    description: "Outlook sendMail + Teams + Graph identity (Admin Agent).",
    docsLink: "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
  },
  {
    id: "paypal",
    name: "PayPal",
    description: "Identity round-trip + payment intents (Procurement).",
    docsLink: "https://developer.paypal.com/dashboard/applications",
  },
];

const REDIRECT_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000")
    .replace(/\/api\/?$/, "") + "/api/v1/integrations/callback";

export default function AdminIntegrationsPage() {
  const router = useRouter();
  const [scope, setScope] = useState<ScopeResponse | null>(null);
  const [configs, setConfigs] = useState<Record<string, ProviderConfig>>({});
  const [configureFor, setConfigureFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refreshConfigs() {
    setBusy(true);
    setError(null);
    try {
      const out: Record<string, ProviderConfig> = {};
      for (const p of OAUTH_PROVIDERS) {
        try {
          out[p.id] = await api.getProviderConfig(p.id);
        } catch (e) {
          // If a provider's GET 404s, leave it absent — UI shows "platform default".
          console.warn(`failed to load config for ${p.id}:`, e);
        }
      }
      setConfigs(out);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void (async () => setScope(await fetchMe()))();
    void refreshConfigs();
  }, []);

  const onSignOut = async () => {
    await signOut();
    router.replace("/sign-in");
  };

  return (
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-5">
          <div>
            <Link
              href="/admin"
              className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wide text-text-muted hover:text-text-primary"
            >
              <ChevronLeft className="h-3 w-3" /> Back to admin
            </Link>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              OAuth app credentials
            </h1>
            <p className="mt-1 text-sm text-text-secondary max-w-2xl">
              Bring your own app: register an OAuth client at each provider,
              then paste the credentials here. The connect flow will run
              through your registration so consent screens, branding, audit
              trails, and revocation stay in your tenancy.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {scope ? (
              <span className="font-mono text-[10px] uppercase tracking-wide text-text-muted">
                Signed in as {scope.user_email} ({scope.role})
              </span>
            ) : null}
            <button
              onClick={() => void onSignOut()}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:text-text-danger"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </header>

        <section className="mt-6 rounded-md border border-border bg-surface-blue p-4 text-sm text-text-secondary">
          <p className="font-mono text-[11px] uppercase tracking-wide text-text-muted">
            Authorised redirect URIs to register at each provider
          </p>
          <ul className="mt-2 space-y-1 font-mono text-[11px]">
            {OAUTH_PROVIDERS.map((p) => (
              <li key={p.id} className="flex items-start gap-2">
                <span className="w-32 shrink-0 text-text-muted">{p.name}</span>
                <code className="text-text-primary">
                  {REDIRECT_BASE}/{p.id}
                </code>
              </li>
            ))}
          </ul>
        </section>

        {error ? (
          <div className="mt-5 rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
            {error}
          </div>
        ) : null}

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {OAUTH_PROVIDERS.map((p) => {
            const cfg = configs[p.id];
            const configured = cfg?.configured ?? false;
            return (
              <div
                key={p.id}
                className="rounded-md border border-border bg-surface p-5"
              >
                <header className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold">{p.name}</h2>
                    <p className="mt-1 text-sm text-text-secondary">
                      {p.description}
                    </p>
                  </div>
                  <span
                    className={
                      configured
                        ? "rounded-sm border border-success/40 bg-surface-blue px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-success"
                        : "rounded-sm border border-border bg-surface px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-text-muted"
                    }
                  >
                    {configured ? "Tenant app" : "Tigeri default"}
                  </span>
                </header>

                <dl className="mt-3 space-y-1.5 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Client ID</dt>
                    <dd className="truncate font-mono text-text-primary">
                      {cfg?.client_id ? cfg.client_id : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Custom redirect URI</dt>
                    <dd className="truncate font-mono text-text-primary">
                      {cfg?.custom_redirect_uri ?? "platform default"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Custom scopes</dt>
                    <dd className="truncate font-mono text-text-primary">
                      {cfg?.custom_scopes && cfg.custom_scopes.length
                        ? `${cfg.custom_scopes.length} override(s)`
                        : "platform default"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <a
                    href={p.docsLink}
                    target="_blank"
                    rel="noreferrer"
                    className="font-mono text-[10px] uppercase tracking-wide text-text-muted hover:text-text-primary"
                  >
                    Open {p.name} app dashboard →
                  </a>
                  <button
                    onClick={() => setConfigureFor(p.id)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-navy px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark"
                  >
                    <Key className="h-3.5 w-3.5" />
                    {configured ? "Update credentials" : "Add credentials"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <p className="mt-6 text-xs text-text-muted">
          <ShieldCheck className="mr-1 inline h-3.5 w-3.5" />
          Secrets are AES-128 (Fernet) encrypted at rest with{" "}
          <code className="font-mono">TIGERI_SECRET_ENCRYPTION_KEY</code>.
          Read endpoints never echo the secret — only the public client_id is
          returned to the UI.
        </p>

        {configureFor ? (
          <ConfigureAppModal
            provider={configureFor}
            providerName={
              OAUTH_PROVIDERS.find((p) => p.id === configureFor)?.name ??
              configureFor
            }
            existing={configs[configureFor]}
            onClose={() => setConfigureFor(null)}
            onSaved={async () => {
              await refreshConfigs();
              setConfigureFor(null);
            }}
            busyParent={busy}
          />
        ) : null}
      </main>

      <GlobalFooter />
    </div>
  );
}

function ConfigureAppModal({
  provider,
  providerName,
  existing,
  onClose,
  onSaved,
  busyParent,
}: {
  provider: string;
  providerName: string;
  existing?: ProviderConfig;
  onClose: () => void;
  onSaved: () => Promise<void>;
  busyParent: boolean;
}) {
  const [clientId, setClientId] = useState(existing?.client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [redirectUri, setRedirectUri] = useState(
    existing?.custom_redirect_uri ?? "",
  );
  const [scopes, setScopes] = useState(
    (existing?.custom_scopes ?? []).join(" "),
  );
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setErr(null);
    setBusy("save");
    try {
      await api.putProviderConfig(provider, {
        client_id: clientId.trim(),
        client_secret: clientSecret,
        custom_redirect_uri: redirectUri.trim() || null,
        custom_scopes: scopes.trim() ? scopes.trim().split(/\s+/) : null,
      });
      await onSaved();
    } catch (e) {
      setErr(_humaniseSaveError((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  const onReset = async () => {
    if (
      !confirm(
        `Drop saved credentials for ${providerName}? Future connects fall back to the Tigeri default app.`,
      )
    )
      return;
    setBusy("reset");
    try {
      await api.deleteProviderConfig(provider);
      await onSaved();
    } catch (e) {
      setErr(_humaniseSaveError((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-md border border-border bg-surface-elevated p-6 shadow-md"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-wide text-text-muted">
              Bring your own app
            </p>
            <h2 className="mt-1 text-base font-semibold tracking-tight">
              {existing?.configured ? "Update" : "Add"} {providerName} OAuth
              credentials
            </h2>
            <p className="mt-1 text-xs text-text-secondary">
              These values come from your provider's app dashboard. Only the
              admin role can change them; secrets are encrypted at rest before
              write.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-sm p-1.5 text-text-secondary hover:bg-background-5 hover:text-text-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <label className="block text-sm font-medium">
            Client ID
            <input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              required
              autoComplete="off"
              spellCheck={false}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-text-primary outline-none transition-colors focus:border-navy"
            />
          </label>
          <label className="block text-sm font-medium">
            Client Secret
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              required
              autoComplete="new-password"
              placeholder={
                existing?.configured ? "(leave blank to keep current)" : ""
              }
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-text-primary outline-none transition-colors focus:border-navy"
            />
            <span className="mt-1 block font-mono text-[10px] uppercase tracking-wide text-text-muted">
              Encrypted at rest with AES-128 (Fernet) before write.
            </span>
          </label>
          <label className="block text-sm font-medium">
            Custom redirect URI (optional)
            <input
              value={redirectUri}
              onChange={(e) => setRedirectUri(e.target.value)}
              placeholder={`${REDIRECT_BASE}/${provider}`}
              autoComplete="off"
              spellCheck={false}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-text-primary outline-none transition-colors focus:border-navy"
            />
            <span className="mt-1 block text-[11px] text-text-muted">
              Leave blank to use the platform default. If you set this, paste
              the same URI into your provider's app dashboard.
            </span>
          </label>
          <label className="block text-sm font-medium">
            Custom scopes (space-separated, optional)
            <textarea
              value={scopes}
              onChange={(e) => setScopes(e.target.value)}
              rows={2}
              spellCheck={false}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-[11px] text-text-primary outline-none transition-colors focus:border-navy"
            />
          </label>

          {err ? (
            <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
              {err}
            </div>
          ) : null}

          <div className="flex items-center justify-between gap-2">
            <div>
              {existing?.configured ? (
                <button
                  type="button"
                  onClick={() => void onReset()}
                  disabled={busy !== null || busyParent}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-danger transition-colors hover:border-danger hover:bg-background-5 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {busy === "reset" ? "Removing…" : "Reset to default"}
                </button>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-background-5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy !== null || busyParent}
                className="inline-flex items-center gap-1 rounded-md bg-navy px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {busy === "save" ? "Saving…" : "Save credentials"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
