export type RequestStatus = "pending" | "approved" | "rejected";

export type AuthTokenResponse = {
  access_token: string;
  token_type?: string;
};

export type AuthMessageResponse = {
  message?: string;
};

export type CurrentUser = {
  id: string;
  email: string;
  name: string;
  provider?: string;
  avatar_url?: string | null;
  client_id?: string | null;
  is_admin: boolean;
  created_at?: string;
};

export type SuggestedAgent = {
  agent: string;
  label: string;
  priority: string;
  reason: string;
};

export type OnboardingStepPayload = {
  stepId: string;
  stepLabel: string;
  forms: Array<{
    formId: string;
    formIndex: number;
    fields: Record<string, unknown>;
  }>;
};

export type OnboardingSubmitPayload = {
  submittedAt: string;
  progress: number;
  serverSavedAt: string;
  schemaVersion: number;
  email: string;
  client_id?: string;
  steps: OnboardingStepPayload[];
};

export type OnboardingSubmitResponse = {
  status: string;
  client_id: string;
  request_id: string;
  message?: string;
  suggested_agents?: SuggestedAgent[];
};

export type ClientStatsResponse = {
  invoices: number;
  expenses: number;
  payments: number;
  total_requests: number;
  success_rate: number;
};

export type ClientLogEntry = {
  agent: string;
  intent: string;
  status: string;
  ref: string;
  at: string;
  message: string
};

export type ClientLogsResponse = {
  logs: ClientLogEntry[];
};

export type ActiveAgent = {
  agent: string;
  label: string;
  priority: string;
  reason: string;
};

export type ClientActiveAgentsResponse = {
  active_agents: ActiveAgent[];
  status: "approved" | "pending" | "rejected";
  admin_notes?: string;
};

export type ClientIntegration = {
  provider: string;
  label: string;
  category: string;
  auth_type: "oauth2" | "apikey";
  connected: boolean;
  connected_at: string | null;
};

export type ClientIntegrationsResponse = {
  integrations: ClientIntegration[];
};

export type ClientRequest = {
  id: string;
  use_case: string;
  agent_type?: string;
  status: RequestStatus;
  admin_notes?: string | null;
  suggested_agents?: SuggestedAgent[];
  created_at: string;
};

export type ClientRequestsResponse = {
  requests: ClientRequest[];
};

export type ClientNewAgentRequestResponse = {
  status: string;
  request_id: string;
  agent: string;
  label: string;
};

export type IntegrationProviderExtraField = {
  key: string;
  label: string;
  placeholder?: string;
};

export type IntegrationProvider = {
  provider: string;
  label: string;
  category: string;
  auth_type: "oauth2" | "apikey";
  field_label?: string;
  field_placeholder?: string;
  extra_fields?: IntegrationProviderExtraField[];
};

export type IntegrationProvidersResponse = {
  providers: IntegrationProvider[];
};

export type ConnectApiKeyPayload = {
  provider: string;
  api_key: string;
  extra?: Record<string, unknown>;
};

export type ProviderConnectionResponse = {
  status: "connected" | "disconnected";
  provider: string;
};

export type OAuthConnectResponse = {
  auth_url: string;
  provider: string;
};

export type WebhookUrlsResponse = {
  webhook_urls: Record<string, string>;
  note?: string;
};

export type AdminDashboardActivity = {
  agent: string;
  display_type?: string;
  intent: string;
  status: string;
  at: string;
};

export type AdminDashboardRecentRequest = {
  id: string;
  client_name: string;
  company: string;
  display_type: string;
  status: RequestStatus;
  date: string;
};

export type AdminDashboardAlert = {
  type: string;
  message: string;
  detail: string;
};

export type AdminDashboardResponse = {
  active_clients: number;
  total_clients: number;
  pending_requests: number;
  success_rate_24h: number;
  total_requests_24h: number;
  recent_activity: AdminDashboardActivity[];
  recent_requests: AdminDashboardRecentRequest[];
  alerts: AdminDashboardAlert[];
};
export type AdminRequest = {
  id: string;
  client_id: string;
  client_name?: string;
  company?: string;
  agent_type?: string;
  display_type?: string;
  status: RequestStatus;
  admin_notes?: string | null;
  suggested_agents?: SuggestedAgent[];
  created_at: string;
};

export type AdminRequestsResponse = {
  requests: AdminRequest[];
};

export type AdminRequestActionResponse = {
  status: RequestStatus;
  client_id?: string;
};

export type AdminClient = {
  id: string;
  name?: string;
  email?: string;
  company?: string;
  active?: boolean;
  created_at?: string;
  [key: string]: unknown;
};

export type AdminClientsResponse = {
  clients: AdminClient[];
};

export type AdminMonitoringAgent = {
  agent?: string;
  label?: string;
  display_type?: string;
  client_count?: number;
  success_rate?: number;
  total_requests?: number;
  last_active?: string;
  status?: string;
  [key: string]: unknown;
};

export type AdminMonitoringResponse = {
  agents: AdminMonitoringAgent[];
};

export type AdminLogEntry = {
  id?: string;
  severity?: string;
  message?: string;
  source?: string;
  at?: string;
  [key: string]: unknown;
};

export type AdminLogsResponse = {
  logs: AdminLogEntry[];
};

export type AdminNavItem = {
  href: string;
  label: string;
  icon: "dashboard" | "requests" | "clients" | "monitoring" | "logs" | "settings" | "shield";
};

export type SidebarUser = {
  initials: string;
  name: string;
  email: string;
  role?: string;
};

export type AdminClientIntegrationStatusResponse = {
  integrations: ClientIntegration[];
};


export type ClientMonitoringAgent = {
  agent: string;
  label: string;
  display_type: string;
  total_requests: number;
  success_rate: number;
  last_active: string;
  status: string;
};

export type ClientMonitoringResponse = {
  agents: ClientMonitoringAgent[];
};

export type ClientSessionInfo = {
  tenant: string;
  region: string;
  environment: string;
  encryption: string;
  connected_systems: string[];
};

export type SystemStatusResponse = {
  maintenance_mode: boolean;
  maintenance_until?: string;
};

// ── Financial Config ──────────────────────────────────────────────────

export type FinancialConfigEmployee = {
  key: string;
  channel: string;
  sender: string;
  name: string;
  employee_id: string;
  dept: string;
};

export type FinancialConfig = {
  base_currency: string;
  tax_rate: number;
  tax_name: string;
  tax_inclusive: boolean;
  fx_enabled: boolean;
  auto_approve_expenses: boolean;
  expense_categories: string[];
  category_code_map: Record<string, string>;
  employees: FinancialConfigEmployee[];
  country: string;
  timezone: string;
};

export type FinancialConfigUpdate = {
  base_currency?: string;
  tax_rate?: number;
  tax_name?: string;
  tax_inclusive?: boolean;
  fx_enabled?: boolean;
  auto_approve_expenses?: boolean;
  expense_categories?: string[];
  category_code_map?: Record<string, string>;
  country?: string;
  timezone?: string;
};

export type FinancialConfigUpdateResponse = {
  status: string;
  fields: string[];
};

export type EmployeeRegisterPayload = {
  channel: string;
  sender: string;
  name: string;
  employee_id?: string;
  dept?: string;
};

export type EmployeeRegisterResponse = {
  status: string;
  key: string;
  name: string;
};

export type EmployeeRemoveResponse = {
  status: string;
  key: string;
};