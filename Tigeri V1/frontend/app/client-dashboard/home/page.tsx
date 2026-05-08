"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Pause, Play } from "lucide-react";
import {
  getClientActiveAgents,
  getClientMonitoring,
  getClientSessionInfo,
  getClientStats,
  pauseClientAgent,
  resumeClientAgent,
} from "@/lib/api";
import type {
  ClientActiveAgentsResponse,
  ClientMonitoringAgent,
  ClientMonitoringResponse,
  ClientSessionInfo,
  ClientStatsResponse,
} from "@/lib/type";
import { formatDateAndTime } from "@/lib/helper";
import NewAgentBanner from "@/components/client-dashboard/NewAgentBanner";
import { ClientHomeSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";
import { useClientDashboardTour } from "@/components/client-dashboard/ClientDashboardTourProvider";

export default function DashboardHomePage() {
  const router = useRouter();
  const { startTour, isRunning: isTourRunning } = useClientDashboardTour();
  const [stats, setStats] = useState<ClientStatsResponse | null>(null);
  const [agentsData, setAgentsData] =
    useState<ClientActiveAgentsResponse | null>(null);
  const [monitoring, setMonitoring] = useState<ClientMonitoringResponse | null>(
    null,
  );
  const [sessionInfo, setSessionInfo] = useState<ClientSessionInfo | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [pausingAgent, setPausingAgent] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [statsRes, agentsRes, monitoringRes, sessionRes] =
          await Promise.all([
            getClientStats(),
            getClientActiveAgents(),
            getClientMonitoring(),
            getClientSessionInfo(),
          ]);
        setStats(statsRes);
        setAgentsData(agentsRes);
        setMonitoring(monitoringRes);
        setSessionInfo(sessionRes);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load dashboard",
        );
      }
    }
    void loadData();
  }, []);

  const onToggleAgent = async (agent: ClientMonitoringAgent) => {
    setPausingAgent(agent.agent);
    try {
      if (agent.status === "paused") {
        await resumeClientAgent(agent.agent);
      } else {
        await pauseClientAgent(agent.agent);
      }
      const refreshed = await getClientMonitoring();
      setMonitoring(refreshed);
    } catch {
    } finally {
      setPausingAgent(null);
    }
  };

  if (error) {
    return <PageErrorState message={error} />;
  }
  if (!stats || !agentsData) return <ClientHomeSkeleton />;

  const statCards = [
    { title: "Invoices", value: String(stats.invoices) },
    { title: "Expenses", value: String(stats.expenses) },
    { title: "Payments", value: String(stats.payments) },
    {
      title: "Success Rate",
      value: `${stats.success_rate}%`,
      caption: `${stats.total_requests} total requests`,
    },
    { title: "Total Agents", value: String(monitoring?.agents.length ?? 0) },
    {
      title: "Active Agents",
      value: String(
        monitoring?.agents.filter((a) => a.status === "active").length ?? 0,
      ),
    },
  ];

  const agents = monitoring?.agents ?? [];

  return (
    <div className="mx-auto w-full max-w-full space-y-4 text-text-primary">
      <NewAgentBanner />
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary">
            Dashboard
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            Overview of your AI agents and activity
          </p>
        </div>
        <button
          type="button"
          onClick={startTour}
          disabled={isTourRunning}
          className="rounded-xs border border-border-10 px-4 py-2 text-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isTourRunning ? "Tour Running" : "Start Tour"}
        </button>
      </div>

      <div className="flex items-center justify-between rounded-xs border border-border-5 bg-background-5 p-3">
        <div>
          <p className="font-medium text-text-primary">
            {agentsData.status === "approved"
              ? "Subscription active"
              : "Awaiting onboarding approval"}
          </p>
          <p className="text-xs text-text-secondary">
            {agentsData.admin_notes ?? "Admin review is in progress."}
          </p>
        </div>
        <button
          onClick={() => router.push("/client-dashboard/request-status")}
          className="rounded-xs bg-background-blue px-4 py-2 text-sm font-medium text-white"
        >
          View Status
        </button>
      </div>

      <div className="grid grid-cols-2 overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-3 lg:grid-cols-6">
        {statCards.map((item, index) => (
          <div
            key={item.title}
            className={`p-5 ${index !== statCards.length - 1 ? "border-r border-border-5" : ""}`}
          >
            <p className="text-3xl font-semibold text-text-primary">
              {item.value}
            </p>
            <p className="mt-2 text-sm text-text-secondary">{item.title}</p>
            {item.caption ? (
              <p className="mt-1 text-xs text-text-success">{item.caption}</p>
            ) : null}
          </div>
        ))}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between px-1">
          <p className="text-lg font-medium text-text-primary">Your Agents</p>
          <button
            onClick={() => router.push("/client-dashboard/new-agent")}
            className="rounded-xs border border-border-10 px-4 py-2 text-sm text-text-primary"
          >
            New Agent Request
          </button>
        </div>

        <div
          className="overflow-hidden rounded-xs border border-border-5 bg-surface"
          data-tour-id="home-agents-table"
        >
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border-5 text-xs uppercase text-text-muted">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Success Rate</th>
                <th className="px-4 py-3">Requests</th>
                <th className="px-4 py-3">Last Active</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent, index) => (
                <tr
                  key={agent.agent}
                  data-tour-id={
                    index === 0 ? "home-agent-row-first" : undefined
                  }
                  onClick={() =>
                    router.push(`/client-dashboard/home/${agent.agent}`)
                  }
                  className={`cursor-pointer hover:bg-background-5 ${index !== agents.length - 1 ? "border-b border-border-5" : ""}`}
                >
                  <td className="px-4 py-3 font-medium text-text-primary">
                    {agent.label}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.display_type}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${agent.status === "active" ? "tag-active" : "tag-paused"}`}
                    >
                      {agent.status === "active" ? (
                        <>
                          <span
                            className="h-1.5 w-1.5 rounded-full bg-current"
                            aria-hidden="true"
                          />
                          Active
                        </>
                      ) : (
                        "Paused"
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.success_rate}%
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.total_requests}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {formatDateAndTime(agent.last_active)}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void onToggleAgent(agent);
                      }}
                      disabled={pausingAgent === agent.agent}
                      className="text-text-muted hover:text-background-blue disabled:opacity-40"
                    >
                      {agent.status === "paused" ? (
                        <Play className="h-4 w-4" />
                      ) : (
                        <Pause className="h-4 w-4" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
              {agents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6">
                    <PageEmptyState
                      title="No agents active yet"
                      message="Request your first agent to start automation workflows."
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      {sessionInfo ? (
        <div>
          <p className="mb-2 px-1 text-lg font-medium text-text-primary">
            Environment Initialisation
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-xs border border-border-5 bg-surface p-4">
              <p className="text-xs uppercase text-text-primary">
                System Login
              </p>
              <div className="mt-3 space-y-2 text-sm">
                {[
                  {
                    label: "Session",
                    value: `ses_${sessionInfo.tenant.toLowerCase().replace(/\s+/g, "_")}_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`,
                  },
                  { label: "Environment", value: sessionInfo.environment },
                  { label: "Encryption", value: sessionInfo.encryption },
                  { label: "Region", value: sessionInfo.region },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="flex items-center justify-between border-b border-border-5 pb-2 last:border-0"
                  >
                    <span className="text-text-muted">{item.label}</span>
                    <span className="text-right text-text-secondary">
                      {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xs border border-border-5 bg-surface p-4">
              <p className="text-xs uppercase text-text-primary">
                Connected Systems
              </p>
              <div className="mt-3 space-y-2 text-sm">
                {sessionInfo.connected_systems.length > 0 ? (
                  sessionInfo.connected_systems.map((system) => (
                    <div
                      key={system}
                      className="flex items-center justify-between border-b border-border-5 pb-2 last:border-0"
                    >
                      <span className="text-text-secondary capitalize">
                        {system}
                      </span>
                      <span className="tag-connected inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs">
                        <span
                          className="h-1.5 w-1.5 rounded-full bg-current"
                          aria-hidden="true"
                        />
                        Connected
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-text-muted">
                    No systems connected.
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
