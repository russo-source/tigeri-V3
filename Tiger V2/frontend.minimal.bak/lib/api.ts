import type {
  ActivationObjectivesResponse,
  ActivationStartResponse,
  AgentCard,
  AuditRecord,
  InvoiceOutput,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TENANT_KEY = "tigeri:tenant_id";

export function getTenantId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_KEY);
}

export function setTenantId(id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TENANT_KEY, id);
}

export function clearTenantId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TENANT_KEY);
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const tenantId = getTenantId();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (tenantId) {
    headers["X-Tigeri-Tenant-Id"] = tenantId;
  }
  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/healthz"),
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
    request<{ state: string; deployed_agents: string[] }>(
      "/activation/deploy",
      { method: "POST", body: JSON.stringify({ agent_ids: agentIds }) },
    ),
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
  listAudit: (params: { trace_id?: string; actor?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.trace_id) qs.set("trace_id", params.trace_id);
    if (params.actor) qs.set("actor", params.actor);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<AuditRecord[]>(`/audit/records${suffix}`);
  },
};

export { ApiError };
