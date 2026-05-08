"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getClientActiveAgents,
  getClientRequests,
  getCurrentUser,
  submitClientNewAgentRequest,
} from "@/lib/api";
import type { ActiveAgent, CurrentUser } from "@/lib/type";
import { ClientNewAgentSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";

const AGENT_CATALOG = [
  {
    key: "a01_invoice",
    label: "Invoice Agent",
    description:
      "Automates invoice generation, reminders, and status tracking.",
  },
  {
    key: "a02_expense",
    label: "Expense Agent",
    description: "Captures receipts, extracts details, and routes approvals.",
  },
  {
    key: "a03_admin",
    label: "Admin Agent",
    description: "Handles admin operations and recurring internal workflows.",
  },
  {
    key: "a04_payment",
    label: "Payment Agent",
    description: "Tracks payment status, reconciliation, and alerts.",
  },
];

function normalizeLabel(value: string) {
  return value.trim().toLowerCase();
}

export default function SettingsPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeAgents, setActiveAgents] = useState<ActiveAgent[]>([]);
  const [activeAgentKeys, setActiveAgentKeys] = useState<string[]>([]);
  const [requestedAgentLabels, setRequestedAgentLabels] = useState<string[]>(
    [],
  );
  const [requestedAgentKeys, setRequestedAgentKeys] = useState<string[]>([]);
  const [requestingAgentKey, setRequestingAgentKey] = useState<string | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const agentByKey = useMemo(
    () => new Map(AGENT_CATALOG.map((agent) => [agent.key, agent])),
    [],
  );

  useEffect(() => {
    async function loadData() {
      try {
        const [userResponse, activeAgentsResponse, requestsResponse] =
          await Promise.all([
            getCurrentUser(),
            getClientActiveAgents(),
            getClientRequests(),
          ]);

        setUser(userResponse);
        setActiveAgents(activeAgentsResponse.active_agents ?? []);
        setActiveAgentKeys(
          Array.from(
            new Set(
              (activeAgentsResponse.active_agents ?? [])
                .map((agent) => (agent.agent ?? "").trim())
                .filter(Boolean),
            ),
          ),
        );

        const pendingRequests = (requestsResponse.requests ?? []).filter(
          (request) => request.status === "pending",
        );

        const pendingLabels = pendingRequests
          .filter((request) => request.status === "pending")
          .map((request) => {
            const requestedKey = request.suggested_agents?.[0]?.agent;
            if (requestedKey && agentByKey.has(requestedKey)) {
              return agentByKey.get(requestedKey)?.label ?? "";
            }
            return (
              request.suggested_agents?.[0]?.label ?? request.agent_type ?? ""
            );
          })
          .filter(Boolean);

        const pendingKeys = pendingRequests
          .map((request) =>
            (
              request.suggested_agents?.[0]?.agent ??
              request.agent_type ??
              ""
            ).trim(),
          )
          .filter((key): key is string => Boolean(key && agentByKey.has(key)));

        setRequestedAgentLabels(Array.from(new Set(pendingLabels)));
        setRequestedAgentKeys(Array.from(new Set(pendingKeys)));
      } catch (loadError) {
        setLoadError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load settings",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, [agentByKey]);

  const acquiredLabels = useMemo(
    () => new Set(activeAgents.map((agent) => normalizeLabel(agent.label))),
    [activeAgents],
  );
  const acquiredKeys = useMemo(
    () => new Set(activeAgentKeys),
    [activeAgentKeys],
  );

  const requestedLabels = useMemo(
    () => new Set(requestedAgentLabels.map((label) => normalizeLabel(label))),
    [requestedAgentLabels],
  );
  const requestedKeysSet = useMemo(
    () => new Set(requestedAgentKeys),
    [requestedAgentKeys],
  );

  const onRequestAgent = async (agentKey: string) => {
    const agent = agentByKey.get(agentKey);
    if (!agent) {
      return;
    }

    const agentLabel = agent.label;
    setSuccess(null);
    setActionError(null);
    const normalized = normalizeLabel(agentLabel);

    if (
      acquiredKeys.has(agentKey) ||
      requestedKeysSet.has(agentKey) ||
      acquiredLabels.has(normalized) ||
      requestedLabels.has(normalized)
    ) {
      return;
    }

    try {
      setRequestingAgentKey(agentKey);
      await submitClientNewAgentRequest(agentKey);

      setRequestedAgentLabels((prev) =>
        prev.includes(agentLabel) ? prev : [...prev, agentLabel],
      );
      setRequestedAgentKeys((prev) =>
        prev.includes(agentKey) ? prev : [...prev, agentKey],
      );
      setSuccess(`${agentLabel} request submitted.`);
    } catch (requestError) {
      setActionError(
        requestError instanceof Error
          ? requestError.message
          : "Failed to submit new agent request",
      );
    } finally {
      setRequestingAgentKey(null);
    }
  };

  const availableAgents = AGENT_CATALOG.filter(
    (agent) =>
      !acquiredKeys.has(agent.key) &&
      !requestedKeysSet.has(agent.key) &&
      !acquiredLabels.has(normalizeLabel(agent.label)) &&
      !requestedLabels.has(normalizeLabel(agent.label)),
  );

  if (isLoading) {
    return <ClientNewAgentSkeleton />;
  }

  if (loadError) {
    return <PageErrorState message={loadError} />;
  }

  if (!user) {
    return (
      <PageEmptyState
        title="User profile unavailable"
        message="Please sign in again and retry."
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">New Agent</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Request agents that are not currently acquired
        </p>
      </div>

      {success ? <p className="text-sm text-emerald-700">{success}</p> : null}
      {actionError ? (
        <p className="text-sm text-red-600">{actionError}</p>
      ) : null}

      <div
        className="rounded-xs border border-border-5 bg-surface p-4"
        data-tour-id="settings-available-agents"
      >
        <p className="text-base font-medium text-text-primary">
          Available Agents
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {AGENT_CATALOG.map((agent, agentIndex) => {
            const normalizedLabel = normalizeLabel(agent.label);
            const isAcquired =
              acquiredKeys.has(agent.key) ||
              acquiredLabels.has(normalizedLabel);
            const isRequested =
              requestedKeysSet.has(agent.key) ||
              requestedLabels.has(normalizedLabel);
            const isAvailable = !isAcquired && !isRequested;

            return (
              <div
                key={agent.key}
                className="rounded-xs border border-border-5 bg-background-5 px-3 py-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-text-primary">
                      {agent.label}
                    </p>
                    <p className="mt-1 text-xs text-text-secondary">
                      {agent.description}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs ${
                      isAcquired
                        ? "tag-acquired"
                        : isRequested
                          ? "tag-requested"
                          : "tag-available"
                    }`}
                  >
                    {isAcquired
                      ? "Acquired"
                      : isRequested
                        ? "Requested"
                        : "Available"}
                  </span>
                </div>

                <button
                  type="button"
                  data-tour-id={
                    agentIndex === 0 ? "settings-request-first" : undefined
                  }
                  onClick={() => void onRequestAgent(agent.key)}
                  disabled={!isAvailable || requestingAgentKey === agent.key}
                  className="mt-3 rounded-xs border border-background-blue px-3 py-1.5 text-sm text-background-blue disabled:cursor-not-allowed disabled:border-border-5 disabled:text-text-muted"
                >
                  {requestingAgentKey === agent.key
                    ? "Submitting..."
                    : isAcquired
                      ? "Already acquired"
                      : isRequested
                        ? "Request sent"
                        : "Request agent"}
                </button>
              </div>
            );
          })}
        </div>

        {availableAgents.length === 0 ? (
          <div className="mt-3">
            <PageEmptyState
              title="No agents left to request"
              message="All available agents are already acquired or pending approval."
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
