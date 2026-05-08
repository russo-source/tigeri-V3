"use client";

import { useEffect, useMemo, useState } from "react";
import { getAdminMonitoring } from "@/lib/api";
import type { AdminMonitoringResponse } from "@/lib/type";
import { formatDate, formatTime } from "@/lib/helper";
import { AdminMonitoringSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";

function getStatusPill(status: string) {
  const value = status.toLowerCase();

  if (value === "active") {
    return "tag-active";
  }

  if (value === "paused") {
    return "tag-paused";
  }

  return "tag-error";
}

export default function AdminMonitoringPage() {
  const [data, setData] = useState<AdminMonitoringResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadMonitoring() {
      try {
        const response = await getAdminMonitoring();
        setData(response);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load monitoring",
        );
      }
    }

    void loadMonitoring();
  }, []);

  const stats = useMemo(() => {
    const agents = data?.agents ?? [];

    return [
      { title: "Total Agents", value: String(agents.length) },
      {
        title: "Active",
        value: String(
          agents.filter(
            (agent) => String(agent.status ?? "").toLowerCase() === "active",
          ).length,
        ),
      },
      {
        title: "Errors",
        value: String(
          agents.filter(
            (agent) => String(agent.status ?? "").toLowerCase() === "error",
          ).length,
        ),
      },
      {
        title: "Avg Success",
        value:
          agents.length > 0
            ? `${(
                agents.reduce(
                  (sum, item) => sum + Number(item.success_rate ?? 0),
                  0,
                ) / agents.length
              ).toFixed(1)}%`
            : "0%",
      },
    ];
  }, [data]);

  if (error) {
    return <PageErrorState message={error} />;
  }

  if (!data) {
    return <AdminMonitoringSkeleton />;
  }

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          Agent Monitoring
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Global agent performance and usage metrics
        </p>
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
            <p className="text-4xl font-semibold text-text-primary">
              {stat.value}
            </p>
            <p className="mt-2 text-sm text-text-secondary">{stat.title}</p>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3 text-sm font-medium text-text-primary">
          All Agents
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border-5 text-xs uppercase text-text-muted">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Success Rate</th>
              <th className="px-4 py-2">Requests</th>
              <th className="px-4 py-2">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {data.agents.length > 0 ? (
              data.agents.map((agent, index) => (
                <tr
                  key={`${agent.agent ?? agent.label ?? "agent"}-${index}`}
                  className={
                    index !== data.agents.length - 1
                      ? "border-b border-border-5"
                      : ""
                  }
                >
                  <td className="px-4 py-3 font-medium text-text-primary">
                    {String(agent.label ?? agent.agent ?? "Unknown")}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {String(agent.display_type ?? agent.agent ?? "-")}
                  </td>

                  <td className="px-4 py-3">
                    {(() => {
                      const statusText = String(agent.status ?? "unknown");
                      const normalizedStatus = statusText.toLowerCase();
                      const displayStatus =
                        normalizedStatus.charAt(0).toUpperCase() +
                        normalizedStatus.slice(1);

                      return (
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${getStatusPill(statusText)}`}
                        >
                          {normalizedStatus === "active" ? (
                            <span
                              className="h-1.5 w-1.5 rounded-full bg-current"
                              aria-hidden="true"
                            />
                          ) : null}
                          {displayStatus}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.success_rate ?? "-"}%
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.total_requests ?? "-"}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {agent.last_active != null ? (
                      <div className="flex gap-2">
                        <span>{formatDate(agent.last_active)}</span>
                        <span>{formatTime(agent.last_active)}</span>
                      </div>
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} className="px-4 py-6">
                  <PageEmptyState
                    title="No agents found"
                    message="Agents will appear after onboarding and activation."
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
