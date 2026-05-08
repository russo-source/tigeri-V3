"use client";

import { useEffect, useState } from "react";
import { getAdminDashboard } from "@/lib/api";
import type { AdminDashboardResponse } from "@/lib/type";
import {
  formatDate,
  formatDateAndTime,
  getStatusPill,
  truncateText,
} from "@/lib/helper";
import { AdminOverviewSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";

function getSeverityPill(status: string) {
  if (status.toLowerCase() === "success") {
    return "tag-success";
  }

  if (status.toLowerCase() === "warning") {
    return "tag-warning";
  }

  if (status.toLowerCase() === "error") {
    return "tag-error";
  }

  if (status.toLowerCase() === "info") {
    return "tag-info";
  }

  return "tag-info";
}

function getTypeTagPill(index: number) {
  const palettes = [
    "tag-type-1",
    "tag-type-2",
    "tag-type-3",
    "tag-type-4",
  ] as const;

  return palettes[index % palettes.length];
}

export default function AdminDashboardOverviewPage() {
  const [data, setData] = useState<AdminDashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDashboard() {
      try {
        const response = await getAdminDashboard();
        setData(response);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load dashboard",
        );
      }
    }

    void loadDashboard();
  }, []);

  if (error) {
    return <PageErrorState message={error} />;
  }

  if (!data) {
    return <AdminOverviewSkeleton />;
  }

  const statCards = [
    { title: "Active Clients", value: String(data.active_clients) },
    { title: "Total Clients", value: String(data.total_clients) },
    { title: "Pending Requests", value: String(data.pending_requests) },
    {
      title: "24h Success Rate",
      value: `${data.success_rate_24h}%`,
      caption: `${data.total_requests_24h} requests in last 24h`,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          Admin Dashboard
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Platform overview and recent activity
        </p>
      </div>

      <div className="grid overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-4">
        {statCards.map((stat, index) => (
          <div
            key={stat.title}
            className={
              index !== statCards.length - 1
                ? "border-r border-border-5 p-5"
                : "p-5"
            }
          >
            <p className="text-4xl font-semibold text-text-primary">
              {stat.value}
            </p>
            <p className="mt-2 text-sm text-text-secondary">{stat.title}</p>
            {stat.caption ? (
              <p className="mt-1 text-xs text-text-secondary">{stat.caption}</p>
            ) : null}
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-12">
        <div className="overflow-hidden rounded-xs border border-border-5 bg-surface lg:col-span-8">
          <div className="flex items-center justify-between border-b border-border-5 px-4 py-3">
            <p className="text-sm font-medium text-text-primary">
              Recent Requests
            </p>
          </div>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border-5 uppercase text-xs text-text-muted">
              <tr>
                <th className="px-4 py-2">Client</th>
                <th className="px-4 py-2">Company</th>
                <th className="px-4 py-2">Type</th>
                <th className="pl-6 py-2">Status</th>
                <th className="px-4 py-2">Date</th>
              </tr>
            </thead>
            <tbody>
              {(data.recent_requests ?? []).length > 0 ? (
                (data.recent_requests ?? []).map((req, index) => (
                  <tr
                    key={req.id}
                    className={
                      index !== data.recent_requests.length - 1
                        ? "border-b border-border-5"
                        : ""
                    }
                  >
                    <td className="px-4 py-3 font-medium text-text-primary">
                      {req.client_name}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {truncateText(String(req.company ?? "-"))}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      <div className="flex flex-wrap gap-2">
                        {(req.display_type ?? "")
                          .split(",")
                          .map((type) => type.trim())
                          .filter(Boolean)
                          .map((type, tagIndex) => (
                            <span
                              key={`${req.id}-${type}`}
                              className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs ${getTypeTagPill(tagIndex)}`}
                            >
                              {type}
                            </span>
                          ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs ${getStatusPill(req.status)}`}
                      >
                        {req.status.charAt(0).toUpperCase() +
                          req.status.slice(1)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {formatDate(req.date)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="px-4 py-6">
                    <PageEmptyState
                      title="No recent requests"
                      message="Client onboarding requests will appear here."
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-4 lg:col-span-4">
          <div className="flex items-center justify-between border-b border-border-5 pb-2">
            <p className="text-sm font-medium text-text-primary">Alerts</p>
            <span className="tag-warning rounded-full px-2 py-0.5 text-xs">
              {(data.alerts ?? []).length}
            </span>
          </div>
          <div className="mt-2 space-y-3">
            {(data.alerts ?? []).map((alert, index) => (
              <div
                key={index}
                className="border-b border-border-5 pb-2 last:border-0"
              >
                <p className="text-sm font-medium text-text-primary">
                  {alert.message}
                </p>
                <p className="text-xs text-text-muted">{alert.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="flex items-center justify-between border-b border-border-5 px-4 py-3">
          <p className="text-sm font-medium text-text-primary">
            Recent Activity
          </p>
        </div>

        <div className="border-b border-border-5 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          <div className="grid grid-cols-[90px_minmax(220px,1fr)_170px] items-center gap-3">
            <span>Status</span>
            <span>Activity</span>
            <span>Time</span>
          </div>
        </div>

        <div>
          {data.recent_activity.map((activity, index) => (
            <div
              key={`${activity.agent}-${activity.intent}-${activity.at}-${index}`}
              className={
                index !== data.recent_activity.length - 1
                  ? "grid grid-cols-[90px_minmax(220px,1fr)_170px] items-center gap-3 border-b border-border-5 px-4 py-3"
                  : "grid grid-cols-[90px_minmax(220px,1fr)_170px] items-center gap-3 px-4 py-3"
              }
            >
              <span
                className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs ${getSeverityPill(activity.status)}`}
              >
                {activity.status}
              </span>
              <p className="min-w-0 text-sm text-text-secondary">
                {activity.display_type ?? activity.agent} handled{" "}
                {activity.intent}
              </p>
              <p className="text-sm text-text-muted">
                {formatDateAndTime(activity.at)}
              </p>{" "}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
