// Tigeri.ai response types — mirror the FastAPI Pydantic models

export type TrustTier =
  | "OBSERVER"
  | "RECOMMENDER"
  | "ACTOR_GATED"
  | "ACTOR_ELEVATED";

export type AgentCard = {
  agent_id: string;
  name: string;
  version: string;
  priority: number;
  phase: string;
  status: string;
  function: string;
  default_trust_tier: TrustTier;
  required_integrations: { category: string; access_pattern: "API" | "MCP" }[];
  delivery_surfaces: ("web" | "mobile")[];
  roi_baseline: string;
};

export type ActivationStateName =
  | "S0_SIGNED_IN"
  | "S1_CRM_DISCOVERY"
  | "S2_MCP_CONNECT"
  | "S2_API_CONNECT"
  | "S3_CAPABILITY_INVENTORY"
  | "S4_OBJECTIVE_INTAKE"
  | "S5_AGENT_REASONING"
  | "S6_RECOMMENDATION_REVIEW"
  | "S7_AGENT_DEPLOY"
  | "S8_ACTIVE"
  | "S_FAIL_NO_CRM"
  | "S_FAIL_INTEGRATION"
  | "S_FAIL_INTROSPECTION"
  | "S_FAIL_NO_MATCH"
  | "S_FAIL_REJECT"
  | "S_FAIL_DEPLOY"
  | "S_TERMINAL_ABORT";

export type CapabilityInventory = {
  tenant_id: string;
  source_system: string;
  access_mode: "MCP" | "API";
  discovered_objects: string[];
  discovered_actions: string[];
  auth_scopes: string[];
  introspection_completed_at: string;
};

export type ActivationStartResponse = {
  state: ActivationStateName;
  inventory: CapabilityInventory | null;
  history: { from: string; to: string; reason: string }[];
};

export type Recommendation = {
  agent_id: string;
  rank: number;
  match_score: number;
  projected_roi: string;
  rationale: string;
  required_integrations_present: boolean;
};

export type ActivationObjectivesResponse = {
  state: ActivationStateName;
  recommendations: {
    tenant_id: string;
    ranked_recommendations: Recommendation[];
    generated_at: string;
  } | null;
};

export type ActivationDeployResponse = {
  state: ActivationStateName;
  deployed_agents: string[];
};

export type InvoiceLineItem = {
  description: string;
  qty: string;
  unit_price: string;
};

export type InvoiceOutput = {
  tenant_id: string;
  invoice_id: string;
  vendor_name: string;
  currency: string;
  amount_total: string;
  tax_total: string;
  line_items: InvoiceLineItem[];
  validation_status: "VALID" | "NEEDS_REVIEW" | "REJECTED";
  approval_status: "PENDING" | "APPROVED" | "DENIED";
  posting_status: "POSTED" | "NOT_POSTED";
  posting_reference: string;
};

export type AuditRecord = {
  id: string;
  actor: string;
  action: string;
  target_resource: string;
  tenant_id: string;
  outcome: string;
  trace_id: string;
  timestamp_utc: string;
  chain_position: number | null;
  backfilled_at: string | null;
};
