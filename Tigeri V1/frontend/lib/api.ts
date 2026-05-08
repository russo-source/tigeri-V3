import type {
  AdminClientIntegrationStatusResponse,
  AdminClientsResponse,
  AdminDashboardResponse,
  AdminLogsResponse,
  AdminMonitoringResponse,
  AdminNavItem,
  AdminRequestActionResponse,
  AdminRequestsResponse,
  AuthMessageResponse,
  AuthTokenResponse,
  ClientActiveAgentsResponse,
  ClientIntegrationsResponse,
  ClientLogEntry,
  ClientLogsResponse,
  ClientMonitoringResponse,
  ClientNewAgentRequestResponse,
  ClientRequestsResponse,
  ClientSessionInfo,
  ClientStatsResponse,
  ConnectApiKeyPayload,
  CurrentUser,
  EmployeeRegisterPayload,
  EmployeeRegisterResponse,
  EmployeeRemoveResponse,
  FinancialConfig,
  FinancialConfigUpdate,
  FinancialConfigUpdateResponse,
  IntegrationProvidersResponse,
  OAuthConnectResponse,
  OnboardingSubmitPayload,
  OnboardingSubmitResponse,
  ProviderConnectionResponse,
  RequestStatus,
  SidebarUser,
  SystemStatusResponse,
  WebhookUrlsResponse,
} from "@/lib/type";
import { API_ENDPOINTS } from "@/lib/api-endpoints";
import { createTraceId, log, logError } from "@/lib/observability";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const ACCESS_TOKEN_KEY = "auth_access_token";
const CURRENT_USER_KEY = "auth_current_user";
const RESOLVED_ROUTE_KEY = "auth_resolved_route";
const USER_ROLE_COOKIE = "auth_user_role";

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  auth?: boolean;
  body?: unknown;
  retry?: boolean;
  signal?: AbortSignal;
  headers?: Record<string, string>;
};

type RequestContext = {
  path: string;
  method: string;
  traceId: string;
  startedAt: number;
  auth: boolean;
};

type RequestInterceptor = (ctx: RequestContext) => void;

const requestInterceptors: RequestInterceptor[] = [];
const responseInterceptors: Array<
  (ctx: RequestContext, response: Response | null, error?: unknown) => void
> = [];

requestInterceptors.push((ctx) => {
  log("debug", "api.request", {
    traceId: ctx.traceId,
    path: ctx.path,
    method: ctx.method,
    auth: ctx.auth,
  });
});

responseInterceptors.push((ctx, response, error) => {
  const durationMs = Date.now() - ctx.startedAt;

  if (error) {
    logError("api.response.error", error, {
      traceId: ctx.traceId,
      path: ctx.path,
      method: ctx.method,
      durationMs,
    });
    return;
  }

  log("info", "api.response", {
    traceId: ctx.traceId,
    path: ctx.path,
    method: ctx.method,
    status: response?.status,
    durationMs,
  });
});

export function registerRequestInterceptor(interceptor: RequestInterceptor) {
  requestInterceptors.push(interceptor);
}

export function registerResponseInterceptor(
  interceptor: (ctx: RequestContext, response: Response | null, error?: unknown) => void
) {
  responseInterceptors.push(interceptor);
}

function normalizePath(path: string) {
  return path.startsWith("/") ? path : `/${path}`;
}

function buildUrl(path: string) {
  const normalizedPath = normalizePath(path);
  if (!API_BASE_URL) {
    return normalizedPath;
  }

  return `${API_BASE_URL}${normalizedPath}`;
}

export function setAccessToken(token: string) {
  if (typeof window === "undefined") {
    return;
  }

  const previousToken = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (previousToken && previousToken !== token) {
    localStorage.removeItem(CURRENT_USER_KEY);
    localStorage.removeItem(RESOLVED_ROUTE_KEY);
  }

  localStorage.setItem(ACCESS_TOKEN_KEY, token);
  document.cookie = `${ACCESS_TOKEN_KEY}=${encodeURIComponent(token)}; path=/; samesite=lax`;
}

export function getAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }

  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function clearAccessToken() {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(CURRENT_USER_KEY);
  localStorage.removeItem(RESOLVED_ROUTE_KEY);
  document.cookie = `${ACCESS_TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; samesite=lax`;
  document.cookie = `${USER_ROLE_COOKIE}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; samesite=lax`;
}

export function setCachedCurrentUser(user: CurrentUser) {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.setItem(CURRENT_USER_KEY, JSON.stringify(user));
  const role = user.is_admin ? "admin" : "client";
  document.cookie = `${USER_ROLE_COOKIE}=${role}; path=/; samesite=lax`;
}

export function getCachedCurrentUser(): CurrentUser | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = localStorage.getItem(CURRENT_USER_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    localStorage.removeItem(CURRENT_USER_KEY);
    return null;
  }
}

export function setCachedResolvedRoute(route: string) {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.setItem(RESOLVED_ROUTE_KEY, route);
}

export function getCachedResolvedRoute(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  return localStorage.getItem(RESOLVED_ROUTE_KEY);
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    const fallback = `Request failed with status ${response.status}`;
    throw new Error(payload?.detail ?? payload?.error ?? payload?.message ?? fallback);
  }

  return payload as T;
}

async function refreshAccessToken() {
  const response = await fetch(buildUrl(API_ENDPOINTS.auth.refresh), {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  const payload = await parseJsonOrThrow<AuthTokenResponse>(response);

  if (payload.access_token) {
    setAccessToken(payload.access_token);
  }

  return payload;
}

function shouldRetry(status: number) {
  return status === 429 || status >= 500;
}

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    auth = false,
    body,
    retry = true,
    signal,
    headers: customHeaders = {},
  } = options;
  const token = getAccessToken();
  const traceId = createTraceId();
  const context: RequestContext = {
    path,
    method,
    traceId,
    startedAt: Date.now(),
    auth,
  };

  for (const interceptor of requestInterceptors) {
    interceptor(context);
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",
    "x-trace-id": traceId,
    ...customHeaders,
  };

  if (auth && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;

  try {
    response = await fetch(buildUrl(path), {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    for (const interceptor of responseInterceptors) {
      interceptor(context, null, error);
    }
    throw error;
  }

  if (auth && response.status === 401 && retry) {
    try {
      await refreshAccessToken();
      return request<T>(path, { ...options, retry: false });
    } catch {
      clearAccessToken();
      throw new Error("Your session has expired. Please sign in again.");
    }
  }

  if (retry && shouldRetry(response.status)) {
    await sleep(400);
    response = await fetch(buildUrl(path), {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  }

  for (const interceptor of responseInterceptors) {
    interceptor(context, response);
  }

  return parseJsonOrThrow<T>(response);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}) {
  return request<T>(path, options);
}

export async function signInWithEmail(email: string, password: string) {
  return request<AuthTokenResponse>(API_ENDPOINTS.auth.login, {
    method: "POST",
    body: { email, password },
  });
}

export async function signUpWithEmail(name: string, email: string, password: string) {
  return request<AuthTokenResponse>(API_ENDPOINTS.auth.register, {
    method: "POST",
    body: { name, email, password },
  });
}

export async function requestPasswordReset(email: string) {
  return request<AuthMessageResponse>(API_ENDPOINTS.auth.forgotPassword, {
    method: "POST",
    body: { email },
  });
}

export async function resetPassword(token: string, newPassword: string) {
  return request<AuthMessageResponse>(API_ENDPOINTS.auth.resetPassword, {
    method: "POST",
    body: { token, new_password: newPassword },
  });
}

export async function logout() {
  try {
    await request<AuthMessageResponse>(API_ENDPOINTS.auth.logout, {
      method: "POST",
      auth: true,
    });
  } finally {
    clearAccessToken();
  }
}

export function googleLoginUrl() {
  return buildUrl(API_ENDPOINTS.auth.googleLogin);
}

export async function getCurrentUser(options?: { force?: boolean }) {
  const force = options?.force ?? false;
  if (!force) {
    const cachedUser = getCachedCurrentUser();
    if (cachedUser) {
      return cachedUser;
    }
  }

  const user = await request<CurrentUser>(API_ENDPOINTS.auth.me, { auth: true });
  setCachedCurrentUser(user);
  return user;
}

export async function joinWaitlist(email: string) {
  return request<{ message: string }>(API_ENDPOINTS.public.waitlist, {
    method: "POST",
    body: { email },
  });
}

export async function submitOnboarding(payload: OnboardingSubmitPayload) {
  return request<OnboardingSubmitResponse>(API_ENDPOINTS.onboarding.submit, {
    method: "POST",
    auth: true,
    body: payload,
  });
}

export async function getClientStats() {
  return request<ClientStatsResponse>(API_ENDPOINTS.client.stats, { auth: true });
}

export async function getClientLogs() {
  return request<ClientLogsResponse>(API_ENDPOINTS.client.logs, { auth: true });
}

export async function getClientActiveAgents() {
  return request<ClientActiveAgentsResponse>(API_ENDPOINTS.client.activeAgents, {
    auth: true,
  });
}

export async function getClientRequests() {
  return request<ClientRequestsResponse>(API_ENDPOINTS.client.requests, { auth: true });
}

export async function submitClientNewAgentRequest(agentKey: string, note?: string) {
  return request<ClientNewAgentRequestResponse>(API_ENDPOINTS.client.newAgentRequest, {
    method: "POST",
    auth: true,
    body: { agent_key: agentKey, note },
  });
}

export async function getClientMonitoring() {
  return request<ClientMonitoringResponse>(API_ENDPOINTS.client.monitoring, { auth: true });
}

export async function getClientConfig() {
  return request<{ active_agents: string[] }>(API_ENDPOINTS.client.config, { auth: true });
}

export async function getClientSessionInfo() {
  return request<ClientSessionInfo>(API_ENDPOINTS.client.sessionInfo, { auth: true });
}

export async function pauseClientAgent(agentName: string) {
  return request<{ status: string }>(API_ENDPOINTS.client.agentPause(agentName), {
    method: "POST",
    auth: true,
  });
}

export async function resumeClientAgent(agentName: string) {
  return request<{ status: string }>(API_ENDPOINTS.client.agentResume(agentName), {
    method: "POST",
    auth: true,
  });
}

export async function getClientSystemStatus() {
  return request<SystemStatusResponse>(API_ENDPOINTS.client.systemStatus);
}

export async function getIntegrationProviders() {
  return request<IntegrationProvidersResponse>(API_ENDPOINTS.integrations.providers);
}

export async function getStripeWebhookUrl() {
  return request<{ webhook_url: string; instructions: string }>(
    API_ENDPOINTS.integrations.stripeWebhookUrl,
    { auth: true }
  );
}

export async function saveStripeWebhookSecret(webhookSecret: string) {
  return request(API_ENDPOINTS.integrations.stripeWebhookSecret, {
    method: "POST",
    auth: true,
    body: { webhook_secret: webhookSecret }
  });
}

export async function getIntegrationStatusByClient(clientId: string) {
  return request<ClientIntegrationsResponse>(API_ENDPOINTS.integrations.statusByClient(clientId), {
    auth: true,
  });
}

export interface OnboardingPreviewResponse {
  suggested_agents: Array<{
    agent: string;
    label: string;
    reason: string;
    priority: "high" | "medium" | "low";
  }>;
  integration_platforms: string[];
  parsed_profile: {
    industry: string;
    integrations: string;
    compliance: string;
  };
}
export async function previewOnboarding(steps: unknown[]) {
  return request<OnboardingPreviewResponse>(API_ENDPOINTS.onboarding.preview, {
    method: "POST",
    auth: true,
    body: { steps },
  });
}

export async function connectApiKeyProvider(payload: ConnectApiKeyPayload) {
  return request<ProviderConnectionResponse>(API_ENDPOINTS.integrations.connectApiKey, {
    method: "POST",
    auth: true,
    body: payload,
  });
}

export async function initiateOAuthProvider(provider: string) {
  return request<OAuthConnectResponse>(API_ENDPOINTS.integrations.connectOAuth(provider), {
    auth: true,
  });
}

export async function disconnectProvider(provider: string) {
  return request<ProviderConnectionResponse>(API_ENDPOINTS.integrations.disconnect(provider), {
    method: "DELETE",
    auth: true,
  });
}

export async function getWebhookUrls() {
  return request<WebhookUrlsResponse>(API_ENDPOINTS.integrations.webhookUrls, {
    auth: true,
  });
}

export async function getAdminDashboard() {
  return request<AdminDashboardResponse>(API_ENDPOINTS.admin.dashboard, { auth: true });
}

export async function getAdminRequests(status?: RequestStatus) {
  const suffix = status ? `?status=${status}` : "";
  return request<AdminRequestsResponse>(`${API_ENDPOINTS.admin.requests}${suffix}`, { auth: true });
}

export async function approveAdminRequest(requestId: string, adminNotes?: string) {
  return request<AdminRequestActionResponse>(API_ENDPOINTS.admin.requestApprove(requestId), {
    method: "PATCH",
    auth: true,
    body: { admin_notes: adminNotes ?? "Approved from TigerScale frontend" },
  });
}

export async function rejectAdminRequest(requestId: string, adminNotes: string) {
  return request<AdminRequestActionResponse>(API_ENDPOINTS.admin.requestReject(requestId), {
    method: "PATCH",
    auth: true,
    body: { admin_notes: adminNotes },
  });
}

export async function getAdminClients() {
  return request<AdminClientsResponse>(API_ENDPOINTS.admin.clients, { auth: true });
}

export async function getAdminMonitoring() {
  return request<AdminMonitoringResponse>(API_ENDPOINTS.admin.monitoring, { auth: true });
}

export async function getAdminLogs(severity?: string) {
  const suffix = severity ? `?severity=${encodeURIComponent(severity)}` : "";
  return request<AdminLogsResponse>(`${API_ENDPOINTS.admin.logs}${suffix}`, { auth: true });
}

export async function getAdminClientIntegrations(clientId: string) {
  return request<AdminClientIntegrationStatusResponse>(
    API_ENDPOINTS.integrations.adminClientIntegrations(clientId),
    { auth: true },
  );
}

export async function adminDisconnectClientProvider(clientId: string, provider: string) {
  return request<ProviderConnectionResponse>(
    API_ENDPOINTS.integrations.adminDisconnectClientProvider(clientId, provider),
    {
      method: "DELETE",
      auth: true,
    },
  );
}

export async function getAdminClientWebhookUrls(clientId: string) {
  return request<WebhookUrlsResponse>(
    API_ENDPOINTS.integrations.adminClientWebhookUrls(clientId),
    {
      auth: true,
    },
  );
}
export async function setAdminClientStatus(clientId: string, active: boolean) {
  return request<{ status: string; client_id: string }>(API_ENDPOINTS.admin.clientsStatus, {
    method: "PATCH",
    auth: true,
    body: { client_id: clientId, active },
  });
}

export async function getAdminToggles() {
  return request<{ maintenance_mode: boolean; maintenance_until?: string }>(
    API_ENDPOINTS.admin.settingsToggles, { auth: true }
  );
}

export async function updateAdminToggles(payload: {
  maintenance_mode?: boolean;
  maintenance_minutes?: number;
}) {
  return request<{ maintenance_mode: boolean; maintenance_until?: string }>(
    API_ENDPOINTS.admin.settingsToggles,
    { method: "PATCH", auth: true, body: payload }
  );
}

export async function getSystemStatus() {
  return request<{ maintenance_mode: boolean; maintenance_until?: string }>(
    API_ENDPOINTS.client.systemStatus
  );
}

export async function setupProviderWebhook(clientId: string, provider: string) {
  return request<{ status: string; provider: string; client_id: string }>(
    API_ENDPOINTS.integrations.setupProviderWebhook(clientId, provider),
    {
      method: "POST",
      auth: true,
    },
  );
}
function getInitials(name: string) {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);

  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "U";
}

export function toSidebarUser(user: CurrentUser): SidebarUser {
  return {
    initials: getInitials(user.name || user.email),
    name: user.name,
    email: user.email,
  };
}

export function toAdminSidebarUser(user: CurrentUser): SidebarUser {
  return {
    ...toSidebarUser(user),
    role: "Admin",
  };
}

export function getAdminNavItems(): AdminNavItem[] {
  return [
    { href: "/admin-dashboard/dashboard", label: "Dashboard", icon: "dashboard" },
    { href: "/admin-dashboard/requests", label: "Requests", icon: "requests" },
    { href: "/admin-dashboard/clients", label: "Clients", icon: "clients" },
    { href: "/admin-dashboard/monitoring", label: "Monitoring", icon: "monitoring" },
    { href: "/admin-dashboard/logs", label: "Logs", icon: "logs" },
    { href: "/admin-dashboard/settings", label: "Settings", icon: "settings" },
    { href: "/admin-dashboard/admin-access", label: "Admin Access", icon: "shield" },
  ];
}

export async function resolveUserRoute(user: CurrentUser): Promise<string> {
  if (user.is_admin) {
    const route = "/admin-dashboard/dashboard";
    setCachedResolvedRoute(route);
    return route;
  }

  try {
    const { status } = await getClientActiveAgents();
    const route = status === "approved" ? "/client-dashboard/home" : "/request-status";
    setCachedResolvedRoute(route);
    return route;
  } catch {
    const route = !user.client_id ? "/onboarding" : "/request-status";
    setCachedResolvedRoute(route);
    return route;
  }
}

export async function bootstrapUserSession() {
  const user = await getCurrentUser({ force: true });
  const route = await resolveUserRoute(user);
  return { user, route };
}

// PayPal
export async function getPaypalWebhookUrl() {
  return request<{ webhook_url: string }>(
    API_ENDPOINTS.integrations.paypalWebhookUrl, { auth: true }
  );
}

export async function testProviderConnection(provider: string) {
  return request<{ status: string; provider: string }>(
    API_ENDPOINTS.integrations.testProvider(provider), { auth: true }
  );
}

export function streamClientLogs(
  onLogs: (logs: ClientLogEntry[]) => void,
  onError?: (err: Error) => void
): () => void {
  const token = getAccessToken();
  let closed = false;
  const ctrl = new AbortController();

  (async () => {
    try {
      const res = await fetch(buildUrl(API_ENDPOINTS.client.logsStream), {
        headers: {
          Authorization: `Bearer ${token ?? ""}`,
          "ngrok-skip-browser-warning": "true",
        },
        credentials: "include",
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) throw new Error(`Stream error: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const line = part.replace(/^data:\s*/, "").trim();
          if (!line || line.startsWith(":")) continue;
          try {
            const parsed = JSON.parse(line) as ClientLogEntry[] | { error: string };
            if (!Array.isArray(parsed)) continue;
            onLogs(parsed);
          } catch { }
        }
      }
    } catch (err) {
      if (!closed) onError?.(err as Error);
    }
  })();

  return () => {
    closed = true;
    ctrl.abort();
  };
}

export function streamClientSystemStatus(
  onStatus: (status: { maintenance_mode: boolean; maintenance_until?: string }) => void,
  onError?: (err: Error) => void,
): () => void {
  let closed = false;
  const ctrl = new AbortController();

  (async () => {
    try {
      const res = await fetch(buildUrl(API_ENDPOINTS.client.systemStatusStream), {
        headers: {
          Accept: "text/event-stream",
          "ngrok-skip-browser-warning": "true",
        },
        credentials: "include",
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) throw new Error(`Stream error: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) {
            continue;
          }
          try {
            const data = JSON.parse(line.slice(6)) as {
              maintenance_mode: boolean;
              maintenance_until?: string;
            };
            onStatus(data);
          } catch {
            // ignore malformed chunks
          }
        }
      }
    } catch (err) {
      if (!closed) onError?.(err as Error);
    }
  })();

  return () => {
    closed = true;
    ctrl.abort();
  };
}

export async function getPendingAdminRequests() {
  return request<{ pending: Array<{ email: string; name: string }> }>(
    API_ENDPOINTS.admin.pendingAccessRequests,
    { auth: true }
  );
}

export async function approveAdminAccessRequest(email: string, secret: string) {
  return request<{ status: string; user_id: string }>(
    API_ENDPOINTS.admin.approveAccessRequest,
    { method: "POST", auth: true, body: { email, secret } }
  );
}

export async function rejectAdminAccessRequest(email: string) {
  return request<{ status: string }>(
    API_ENDPOINTS.admin.rejectAccessRequest,
    { method: "POST", auth: true, body: { email } }
  );
}

export async function requestAdminAccess(payload: {
  email: string;
  name: string;
  password: string;
}) {
  return request<{ status: string; message: string }>(
    API_ENDPOINTS.admin.requestAccess,
    { method: "POST", body: payload }
  );
}

export async function getWebhookSetupGuide(provider: string) {
  return request<{
    provider: string;
    webhook_url: string;
    steps: string[];
    requires_secret: boolean;
    secret_label?: string;
    secret_placeholder?: string;
  }>(API_ENDPOINTS.integrations.webhookSetupGuide(provider), { auth: true });
}

export interface ApproverConfig {
  approver_chat_id: string | null;
  approver_whatsapp: string | null;
  approve_email: string | null;
}

export async function getApproverConfig(): Promise<ApproverConfig> {
  return request<ApproverConfig>(API_ENDPOINTS.approver.config, { auth: true });
}

export async function updateApproverConfig(
  payload: Partial<ApproverConfig>
): Promise<ApproverConfig> {
  return request<ApproverConfig>(API_ENDPOINTS.approver.config, {
    method: "PATCH",
    auth: true,
    body: payload,
  });
}

// ── Financial Config ──────────────────────────────────────────────────

export async function getFinancialConfig(): Promise<FinancialConfig> {
  return request<FinancialConfig>(API_ENDPOINTS.financialConfig.get, { auth: true });
}

export async function updateFinancialConfig(
  payload: FinancialConfigUpdate
): Promise<FinancialConfigUpdateResponse> {
  return request<FinancialConfigUpdateResponse>(API_ENDPOINTS.financialConfig.update, {
    method: "PUT",
    auth: true,
    body: payload,
  });
}

export async function addEmployee(
  payload: EmployeeRegisterPayload
): Promise<EmployeeRegisterResponse> {
  return request<EmployeeRegisterResponse>(API_ENDPOINTS.financialConfig.addEmployee, {
    method: "POST",
    auth: true,
    body: payload,
  });
}

export async function removeEmployee(
  channel: string,
  sender: string
): Promise<EmployeeRemoveResponse> {
  return request<EmployeeRemoveResponse>(API_ENDPOINTS.financialConfig.removeEmployee, {
    method: "DELETE",
    auth: true,
    body: { channel, sender },
  });
}