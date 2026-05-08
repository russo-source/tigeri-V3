import type {
  ActivationDeployResponse,
  ActivationObjectivesResponse,
  ActivationStartResponse,
  AgentCard,
  AuditRecord,
  InvoiceOutput,
} from "./type";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const TENANT_KEY = "tigeri:tenant_id";
const USER_KEY = "tigeri:user_id";
const SESSION_KEY = "tigeri:session_id";

export function getTenantId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_KEY);
}

export function setTenantId(id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TENANT_KEY, id);
}

export function getUserId(): string {
  if (typeof window === "undefined") return "anonymous";
  return window.localStorage.getItem(USER_KEY) ?? "anonymous";
}

export function setUserId(id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_KEY, id);
}

export function getSessionId(): string {
  if (typeof window === "undefined") return "default";
  let sid = window.localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = `s_${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TENANT_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.localStorage.removeItem(SESSION_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Routes that legitimately request /auth/* without an existing session.
 * A 401 from these is normal (e.g. /auth/me probing on first load) — don't
 * eject the user to /sign-in for it. */
const _AUTH_PROBE_PREFIXES = ["/auth/me", "/auth/sign-in", "/auth/sign-up"];

function _maybeBounceToSignIn(path: string): void {
  if (typeof window === "undefined") return;
  if (_AUTH_PROBE_PREFIXES.some((p) => path.startsWith(p))) return;
  // Already on sign-in / sign-up — don't loop.
  if (window.location.pathname.startsWith("/sign-in")) return;
  if (window.location.pathname.startsWith("/sign-up")) return;
  // Hard navigation — drops any in-flight requests too.
  window.location.assign(
    `/sign-in?next=${encodeURIComponent(window.location.pathname)}`,
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const tenantId = getTenantId();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (tenantId) headers["X-Tigeri-Tenant-Id"] = tenantId;
  headers["X-Tigeri-User-Id"] = getUserId();
  headers["X-Tigeri-Session-Id"] = getSessionId();

  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!res.ok) {
    if (res.status === 401) {
      // Stale or missing session — kick the user back to sign-in. Returning
      // ?next= so they can land back on the page they were viewing.
      _maybeBounceToSignIn(path);
    }
    let detail = res.statusText;
    let parsedBody: unknown = null;
    try {
      const body = await res.text();
      try {
        const parsed = JSON.parse(body);
        parsedBody = parsed;
        detail = parsed.detail ?? parsed.error ?? parsed.message ?? body;
      } catch {
        detail = body || detail;
      }
    } catch {
      /* swallow */
    }
    // Server signals the user must change their password before doing
    // anything else. Bounce to /change-password unless we're already there
    // or calling /auth/change-password itself.
    if (
      res.status === 403 &&
      typeof parsedBody === "object" &&
      parsedBody !== null &&
      (parsedBody as { code?: string }).code === "password_change_required" &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/change-password") &&
      !path.startsWith("/auth/change-password")
    ) {
      window.location.assign(
        `/change-password?next=${encodeURIComponent(window.location.pathname)}`,
      );
    }
    throw new ApiError(res.status, String(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/healthz"),
  changePassword: (current_password: string, new_password: string) =>
    request<undefined>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  listAgents: () => request<AgentCard[]>("/agents"),
  getAgentCard: (agentId: string) =>
    request<AgentCard>(`/agents/${agentId}/card`),
  startActivation: (body: {
    source_system: string;
    api_base_url?: string | null;
    mcp_endpoint?: string | null;
  }) =>
    request<ActivationStartResponse>("/activation/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  submitObjectives: (body: {
    industry: string;
    employee_count: number;
    venues_or_locations: number;
    regulated: boolean;
    objectives: { objective: string; priority: "HIGH" | "MEDIUM" | "LOW" }[];
  }) =>
    request<ActivationObjectivesResponse>("/activation/objectives", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deployAgents: (agentIds: string[]) =>
    request<ActivationDeployResponse>("/activation/deploy", {
      method: "POST",
      body: JSON.stringify({ agent_ids: agentIds }),
    }),
  invokeInvoice: (body: {
    tenant_id: string;
    source: "EMAIL" | "UPLOAD" | "API";
    document: { media_type: string; content_ref: string };
    received_at: string;
  }) =>
    request<InvoiceOutput>("/agents/invoice_agent/invoke", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listAudit: (
    params: { trace_id?: string; actor?: string; limit?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.trace_id) qs.set("trace_id", params.trace_id);
    if (params.actor) qs.set("actor", params.actor);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<AuditRecord[]>(`/audit/records${suffix}`);
  },
  integrationsStatus: () =>
    request<
      Record<
        string,
        {
          connected: boolean;
          expires_at?: string;
          is_expired?: boolean;
          meta?: Record<string, string>;
        }
      >
    >("/v1/integrations/status"),
  connectXeroUrl: () => {
    const tid = getTenantId();
    const qs = tid ? `?tenant_id=${encodeURIComponent(tid)}` : "";
    return `${BASE_URL}/v1/integrations/connect/xero${qs}`;
  },
  connectProviderUrl: (provider: string) => {
    const tid = getTenantId();
    const qs = tid ? `?tenant_id=${encodeURIComponent(tid)}` : "";
    return `${BASE_URL}/v1/integrations/connect/${provider}${qs}`;
  },
  disconnectXero: () =>
    request<{ disconnected: boolean }>("/v1/integrations/xero", {
      method: "DELETE",
    }),
  disconnectProvider: (provider: string) =>
    request<{ disconnected: boolean }>(`/v1/integrations/${provider}`, {
      method: "DELETE",
    }),
  connectDemo: (provider: string) =>
    request<{
      connected: boolean;
      mode: string;
      provider: string;
      meta: Record<string, string>;
    }>(`/v1/integrations/connect-demo/${provider}`, { method: "POST" }),
  // ---- Admin user management (admin role required) --------------------
  adminListUsers: (tenantId: string) =>
    request<
      {
        id: string;
        tenant_id: string;
        email: string;
        name: string;
        role: string;
        status: string;
        email_verified: boolean;
        last_active_at: string | null;
        created_at: string;
      }[]
    >(`/admin/tenants/${encodeURIComponent(tenantId)}/users`),

  adminCreateUser: (
    tenantId: string,
    payload: {
      email: string;
      name: string;
      role?: "owner" | "admin" | "member";
      password?: string;
    },
  ) =>
    request<{
      user: {
        id: string;
        tenant_id: string;
        email: string;
        name: string;
        role: string;
        status: string;
        email_verified: boolean;
        last_active_at: string | null;
        created_at: string;
      };
      initial_password: string;
      auto_generated: boolean;
    }>(`/admin/tenants/${encodeURIComponent(tenantId)}/users`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminUpdateUser: (
    userId: string,
    payload: {
      name?: string;
      role?: "owner" | "admin" | "member";
      status?: "invited" | "active" | "suspended" | "offboarded";
    },
  ) =>
    request<{
      id: string;
      tenant_id: string;
      email: string;
      name: string;
      role: string;
      status: string;
      email_verified: boolean;
      last_active_at: string | null;
      created_at: string;
    }>(`/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  adminResetUserPassword: (userId: string, password?: string) =>
    request<{
      user_id: string;
      new_password: string;
      auto_generated: boolean;
    }>(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password: password ?? null }),
    }),

  adminOffboardUser: (userId: string) =>
    request<undefined>(`/admin/users/${encodeURIComponent(userId)}`, {
      method: "DELETE",
    }),

  adminListTenants: () =>
    request<
      {
        id: string;
        slug: string;
        name: string;
        region: string;
        plan: string;
        status: string;
        created_at: string;
      }[]
    >("/admin/tenants"),

  // ---- Bring-Your-Own-App OAuth client config (per provider) -----------
  getProviderConfig: (provider: string) =>
    request<{
      provider: string;
      configured: boolean;
      source: "tenant" | "platform";
      client_id: string;
      custom_redirect_uri: string | null;
      custom_scopes: string[] | null;
    }>(`/v1/integrations/${provider}/config`),
  putProviderConfig: (
    provider: string,
    payload: {
      client_id: string;
      client_secret: string;
      custom_redirect_uri?: string | null;
      custom_scopes?: string[] | null;
    },
  ) =>
    request<{
      provider: string;
      configured: boolean;
      source: "tenant" | "platform";
      client_id: string;
      custom_redirect_uri: string | null;
      custom_scopes: string[] | null;
    }>(`/v1/integrations/${provider}/config`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteProviderConfig: (provider: string) =>
    request<{ removed: boolean; provider: string }>(
      `/v1/integrations/${provider}/config`,
      { method: "DELETE" },
    ),
  telegramLinkCode: () =>
    request<{ code: string; expires_at: string; instructions: string }>(
      "/v1/integrations/telegram/link-code",
      { method: "POST" },
    ),
  whatsappWhoami: () => request<unknown>("/v1/integrations/whatsapp/whoami"),
  whatsappOptin: (recipient_msisdn: string, note = "") =>
    request<{ ok: boolean; recipient_msisdn: string }>(
      "/v1/integrations/whatsapp/optin",
      {
        method: "POST",
        body: JSON.stringify({ recipient_msisdn, note }),
      },
    ),
  whatsappTestSend: (text: string) =>
    request<unknown>("/v1/integrations/whatsapp/test-send", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  integrationsHealth: () =>
    request<{
      summary: { connected: number; healthy: number; failing: number; total: number };
      providers: {
        provider: string;
        connected: boolean;
        healthy: boolean | null;
        latency_ms: number | null;
        error: string | null;
        meta: Record<string, string>;
      }[];
    }>("/v1/integrations/health"),
  adminFeedback: (params: { rating?: 1 | -1; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.rating !== undefined) qs.set("rating", String(params.rating));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<
      {
        id: string;
        rating: number;
        comment: string;
        tenant_id: string;
        user_id: string;
        created_at: string;
        message_id: string;
        message_preview: string;
        user_message_preview: string;
        actions: {
          kind: string;
          tool?: string;
          agent_id?: string;
          summary?: string;
          ok?: boolean;
        }[];
      }[]
    >(`/chat/admin/feedback${suffix}`);
  },
};
