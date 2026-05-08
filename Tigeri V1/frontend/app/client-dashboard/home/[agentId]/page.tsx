"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Pause, Play } from "lucide-react";
import {
  getClientMonitoring,
  pauseClientAgent,
  resumeClientAgent,
  streamClientLogs,
} from "@/lib/api";
import { ClientAgentDetailSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";
import type { ClientLogEntry, ClientMonitoringAgent } from "@/lib/type";
import { formatDateAndTime } from "@/lib/helper";

export default function AgentDetailPage() {
  const router = useRouter();
  const params = useParams<{ agentId: string }>();
  const agentId = params?.agentId;

  const [agents, setAgents] = useState<ClientMonitoringAgent[]>([]);
  const [logs, setLogs] = useState<ClientLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);
  useEffect(() => {
    let allLogs: ClientLogEntry[] = [];

    void (async () => {
      try {
        const monitoringRes = await getClientMonitoring(); // remove getClientLogs()
        setAgents(monitoringRes.agents);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setIsLoading(false);
      }
    })();

    const stop = streamClientLogs(
      (incoming) => {
        allLogs = [...incoming, ...allLogs].filter(
          (l, i, arr) =>
            arr.findIndex(
              (x) =>
                x.at === l.at && x.intent === l.intent && x.agent === l.agent,
            ) === i,
        );
        setLogs(allLogs.filter((l) => l.agent === agentId));
      },
      (err) => setError(err.message),
    );

    return stop;
  }, [agentId]);

  const agent = useMemo(
    () => agents.find((a) => a.agent === agentId),
    [agentId, agents],
  );
  const agentLogs = useMemo(
    () => logs.filter((l) => l.agent === agentId),
    [agentId, logs],
  );

  const onToggle = async () => {
    if (!agent) return;
    setToggling(true);
    try {
      if (agent.status === "paused") {
        await resumeClientAgent(agent.agent);
      } else {
        await pauseClientAgent(agent.agent);
      }
      const refreshed = await getClientMonitoring();
      setAgents(refreshed.agents);
    } finally {
      setToggling(false);
    }
  };

  if (isLoading) return <ClientAgentDetailSkeleton />;
  if (error) return <PageErrorState message={error} />;
  if (!agent) {
    return (
      <PageEmptyState
        title="Agent not found"
        message="The requested agent is unavailable or not assigned to this account."
        actionLabel="Back to dashboard"
        onAction={() => router.replace("/client-dashboard/home")}
      />
    );
  }

  const stats = [
    { title: "Success Rate", value: `${agent.success_rate}%` },
    { title: "Total Requests", value: String(agent.total_requests) },
    { title: "Status", value: agent.status === "active" ? "Active" : "Paused" },
    { title: "Last Active", value: formatDateAndTime(agent.last_active) },
  ];

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-text-primary">
              {agent.label}
            </h1>
            <span
              className={`rounded-full px-3 py-1 text-xs ${agent.status === "active" ? "tag-active" : "tag-paused"}`}
            >
              {agent.status === "active" ? "Active" : "Paused"}
            </span>
          </div>
          <p className="mt-1 text-sm text-text-secondary">
            {agent.display_type} · Created from onboarding
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            data-tour-id="agent-detail-toggle-button"
            onClick={() => void onToggle()}
            disabled={toggling}
            className="inline-flex items-center gap-1 rounded-xs border border-border-5 bg-surface px-3 py-2 text-sm text-text-primary disabled:opacity-50"
          >
            {agent.status === "paused" ? (
              <Play className="h-3.5 w-3.5" />
            ) : (
              <Pause className="h-3.5 w-3.5" />
            )}
            {agent.status === "paused" ? "Resume" : "Pause"}
          </button>
        </div>
      </div>

      <div className="grid overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-4">
        {stats.map((stat, index) => (
          <div
            key={stat.title}
            className={
              index !== stats.length - 1
                ? "border-r border-border-5 p-5"
                : "p-5"
            }
          >
            <p className="text-2xl font-semibold text-text-primary">
              {stat.value}
            </p>
            <p className="mt-2 text-sm text-text-secondary">{stat.title}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3 text-sm font-medium text-text-primary">
          Agent Logs
        </div>
        <div className="border-b border-border-5 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          <div className="grid grid-cols-[88px_minmax(140px,1fr)_minmax(180px,2fr)_140px] items-center gap-3">
            <span>Status</span>
            <span>Intent</span>
            <span>Message</span>
            <span>Time</span>
          </div>
        </div>
        <div className="divide-y divide-border-5 px-3 py-2">
          {agentLogs.length > 0 ? (
            agentLogs.map((log, index) => (
              <div
                key={`${log.ref ?? ""}-${index}`}
                className="grid grid-cols-[88px_minmax(140px,1fr)_minmax(180px,2fr)_140px] items-center gap-3 py-2"
              >
                <span
                  className={`inline-flex w-fit shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${log.status === "success" ? "tag-success" : "tag-error"}`}
                >
                  {log.status}
                </span>
                <p className="min-w-0 truncate text-sm font-medium text-text-primary">
                  {log.intent}
                </p>
                <p className="min-w-0 truncate text-sm text-text-secondary">
                  {log.message}
                </p>
                <p className="text-sm text-text-muted">
                  {formatDateAndTime(log.at ?? "")}
                </p>
              </div>
            ))
          ) : (
            <div className="py-4">
              <PageEmptyState
                title="No logs yet"
                message="Logs will appear here as this agent handles workflows."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
