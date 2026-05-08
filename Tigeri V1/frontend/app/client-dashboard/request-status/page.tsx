"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle, Eye, Send } from "lucide-react";
import { getClientActiveAgents, getClientRequests } from "@/lib/api";
import type { ClientRequest, RequestStatus } from "@/lib/type";
import { formatDate } from "@/lib/helper";
import { ClientRequestStatusSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";

const timelineIcons = { submitted: Send, review: Eye, approved: CheckCircle };

function toTitleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function RequestStatusPage() {
  const [requests, setRequests] = useState<ClientRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [requestsRes] = await Promise.all([
          getClientRequests(),
          getClientActiveAgents(),
        ]);
        setRequests(requestsRes.requests);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load request status",
        );
      } finally {
        setIsLoading(false);
      }
    }
    void loadData();
  }, []);

  const latestRequest = useMemo(
    () =>
      [...requests].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )[0],
    [requests],
  );

  if (isLoading) return <ClientRequestStatusSkeleton />;
  if (error) return <PageErrorState message={error} />;
  if (!latestRequest)
    return (
      <PageEmptyState
        title="No requests found"
        message="Submit a request to start onboarding."
      />
    );

  const timeline: Array<{
    stage: keyof typeof timelineIcons;
    title: string;
    date: string;
  }> = [
    {
      stage: "submitted",
      title: "Request Submitted",
      date: latestRequest.created_at,
    },
    { stage: "review", title: "Under Review", date: latestRequest.created_at },
  ];

  if (latestRequest.status === "approved") {
    timeline.push({
      stage: "approved",
      title: "Approved",
      date: latestRequest.created_at,
    });
  }

  const statusLabel: RequestStatus = latestRequest.status;

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          Request Status
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Track the progress of your onboarding request
        </p>
      </div>

      <div
        className="rounded-xs border border-border-5 bg-surface p-4 md:p-5"
        data-tour-id="request-status-card"
      >
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-[0.12em] text-text-muted">
            Request ID
          </p>
          <span
            className={`rounded-full px-3 py-1 text-xs ${statusLabel === "approved" ? "tag-approved" : statusLabel === "rejected" ? "tag-rejected" : "tag-pending"}`}
          >
            {toTitleCase(statusLabel)}
          </span>
        </div>
        <p className="mt-1 text-sm font-medium text-text-primary">
          {String(latestRequest.id).slice(0, 8)}...
        </p>

        <div className="mt-5 space-y-4">
          {timeline.map((item, index) => {
            const Icon = timelineIcons[item.stage];
            return (
              <div key={item.stage} className="relative flex items-start gap-3">
                <span className="relative z-10 rounded-full bg-background-blue p-1.5 text-white">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <div>
                  <p className="text-sm font-medium text-text-primary">
                    {item.title}
                  </p>
                  <p className="mt-0.5 text-sm text-text-muted">
                    {formatDate(item.date)}
                  </p>
                </div>
                {index !== timeline.length - 1 ? (
                  <span className="absolute left-3 top-7 h-8 w-0.5 bg-background-blue" />
                ) : null}
              </div>
            );
          })}
        </div>

        {latestRequest.admin_notes ? (
          <div className="mt-5 rounded-xs border border-border-5 bg-background-5 p-3">
            <p className="text-xs text-text-muted">Admin Notes</p>
            <p className="mt-1 text-sm text-text-secondary">
              {latestRequest.admin_notes}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
