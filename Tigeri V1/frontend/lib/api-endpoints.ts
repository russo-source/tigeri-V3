const API_V1_PREFIX = "/api/v1";
const CLIENT_PREFIX = "/client";
const ADMIN_PREFIX = "/admin";
const ONBOARDING_PREFIX = "/onboarding";

const withV1 = (path: string) => `${API_V1_PREFIX}${path}`;

export const API_ENDPOINTS = {
  prefixes: {
    apiV1: API_V1_PREFIX,
  },
  auth: {
    login: withV1("/auth/login"),
    register: withV1("/auth/register"),
    refresh: withV1("/auth/refresh"),
    me: withV1("/auth/me"),
    logout: withV1("/auth/logout"),
    forgotPassword: withV1("/auth/forgot-password"),
    resetPassword: withV1("/auth/reset-password"),
    googleLogin: withV1("/auth/google/login"),
  },
  public: {
    waitlist: "/api/waitlist",
  },
  onboarding: {
    submit: `${ONBOARDING_PREFIX}/submit`,
    preview: `${ONBOARDING_PREFIX}/preview`,
  },
  client: {
    stats: `${CLIENT_PREFIX}/stats`,
    logs: `${CLIENT_PREFIX}/logs`,
    logsStream: `${CLIENT_PREFIX}/logs/stream`,
    activeAgents: `${CLIENT_PREFIX}/active-agents`,
    requests: `${CLIENT_PREFIX}/requests`,
    newAgentRequest: `${CLIENT_PREFIX}/requests/new-agent`,
    monitoring: `${CLIENT_PREFIX}/monitoring`,
    config: `${CLIENT_PREFIX}/config`,
    sessionInfo: `${CLIENT_PREFIX}/session-info`,
    systemStatus: `${CLIENT_PREFIX}/system-status`,
    systemStatusStream: `${CLIENT_PREFIX}/system-status/stream`,
    agentPause: (agentName: string) => `${CLIENT_PREFIX}/agent/${agentName}/pause`,
    agentResume: (agentName: string) => `${CLIENT_PREFIX}/agent/${agentName}/resume`,
  },
  integrations: {
    providers: withV1("/integrations/providers"),
    stripeWebhookUrl: withV1("/integrations/stripe/webhook-url"),
    stripeWebhookSecret: withV1("/integrations/stripe/webhook-secret"),
    statusByClient: (clientId: string) => withV1(`/integrations/status/${clientId}`),
    connectApiKey: withV1("/integrations/connect/apikey"),
    connectOAuth: (provider: string) => withV1(`/integrations/connect/${provider}`),
    disconnect: (provider: string) => withV1(`/integrations/disconnect/${provider}`),
    webhookUrls: withV1("/integrations/webhook-urls"),
    paypalWebhookUrl: withV1("/integrations/paypal/webhook-url"),
    testProvider: (provider: string) => withV1(`/integrations/test/${provider}`),
    adminClientIntegrations: (clientId: string) =>
      withV1(`/integrations/admin/integrations/${clientId}`),
    adminDisconnectClientProvider: (clientId: string, provider: string) =>
      withV1(`/integrations/admin/integrations/${clientId}/${provider}`),
    adminClientWebhookUrls: (clientId: string) =>
      withV1(`/integrations/admin/integrations/${clientId}/webhook-urls`),
    setupProviderWebhook: (clientId: string, provider: string) =>
      withV1(`/integrations/admin/integrations/${clientId}/setup-webhook/${provider}`),
    webhookSetupGuide: (provider: string) => withV1(`/integrations/webhook-setup/${provider}`),
  },
  admin: {
    dashboard: `${ADMIN_PREFIX}/dashboard`,
    requests: `${ADMIN_PREFIX}/requests`,
    requestApprove: (requestId: string) => `${ADMIN_PREFIX}/requests/${requestId}/approve`,
    requestReject: (requestId: string) => `${ADMIN_PREFIX}/requests/${requestId}/reject`,
    clients: `${ADMIN_PREFIX}/clients`,
    clientsStatus: `${ADMIN_PREFIX}/clients/status`,
    monitoring: `${ADMIN_PREFIX}/monitoring`,
    logs: `${ADMIN_PREFIX}/logs`,
    settingsToggles: `${ADMIN_PREFIX}/settings/toggles`,
    pendingAccessRequests: withV1("/admin/pending-requests"),
    approveAccessRequest: withV1("/admin/approve"),
    rejectAccessRequest: withV1("/admin/reject"),
    requestAccess: withV1("/admin/request-access"),
  },
  approver: {
    config: withV1("/client/approver-config"),
  },
  financialConfig: {
    get: `${CLIENT_PREFIX}/financial-config`,
    update: `${CLIENT_PREFIX}/financial-config`,
    defaults: `${CLIENT_PREFIX}/financial-config/defaults`,
    addEmployee: `${CLIENT_PREFIX}/financial-config/employee`,
    removeEmployee: `${CLIENT_PREFIX}/financial-config/employee`,
  },
  conversation: {
    history: withV1("/conversations/history"),
    summarize: withV1("/conversations/summarize"),
    embeddings: withV1("/conversations/embeddings"),
    channelSync: withV1("/conversations/channel-sync"),
  },
} as const;
