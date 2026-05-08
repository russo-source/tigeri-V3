"use client";

import { useEffect, useMemo, useState } from "react";
import {
  approveAdminRequest,
  getAdminRequests,
  rejectAdminRequest,
} from "@/lib/api";
import type { AdminRequest, RequestStatus } from "@/lib/type";
import { formatDate, truncateText } from "@/lib/helper";
import { AdminRequestsSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";
import { X } from "lucide-react";

function getStatusPill(status: RequestStatus) {
  if (status === "approved") {
    return "tag-approved";
  }

  if (status === "pending") {
    return "tag-pending";
  }

  return "tag-rejected";
}

function toLabel(status: RequestStatus) {
  return status.charAt(0).toUpperCase() + status.slice(1);
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

export default function AdminRequestsPage() {
  const [requests, setRequests] = useState<AdminRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [activeTab, setActiveTab] = useState("all");
  const [note, setNote] = useState("");
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    async function loadData() {
      try {
        setError(null);
        const requestData = await getAdminRequests();
        setRequests(requestData.requests);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load requests",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, []);

  const filteredRequests = useMemo(() => {
    if (activeTab === "all") {
      return requests;
    }

    return requests.filter((request) => request.status === activeTab);
  }, [activeTab, requests]);

  const selectedRequest = selectedRequestId
    ? (requests.find((request) => request.id === selectedRequestId) ?? null)
    : null;
  const showDetailPanel = Boolean(selectedRequest);

  const tabItems = [
    { id: "all", label: `All (${requests.length})` },
    {
      id: "pending",
      label: `Pending (${requests.filter((request) => request.status === "pending").length})`,
    },
    {
      id: "approved",
      label: `Approved (${requests.filter((request) => request.status === "approved").length})`,
    },
    {
      id: "rejected",
      label: `Rejected (${requests.filter((request) => request.status === "rejected").length})`,
    },
  ];

  const onApprove = async () => {
    if (!selectedRequest || isApproving || isRejecting) {
      return;
    }

    try {
      setIsApproving(true);
      await approveAdminRequest(selectedRequest.id, note || undefined);
      const refreshed = await getAdminRequests();
      setRequests(refreshed.requests);
      setSelectedRequestId(null);
      setNote("");
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Failed to approve request",
      );
    } finally {
      setIsApproving(false);
    }
  };

  const onReject = async () => {
    if (!selectedRequest || isApproving || isRejecting) {
      return;
    }

    try {
      setIsRejecting(true);
      await rejectAdminRequest(
        selectedRequest.id,
        note || "Rejected from TigerScale frontend",
      );
      const refreshed = await getAdminRequests();
      setRequests(refreshed.requests);
      setSelectedRequestId(null);
      setNote("");
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : "Failed to reject request",
      );
    } finally {
      setIsRejecting(false);
    }
  };

  if (isLoading) {
    return <AdminRequestsSkeleton />;
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Requests</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Review and manage onboarding requests
        </p>
      </div>

      {error ? <PageErrorState message={error} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        {tabItems.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={
              activeTab === tab.id
                ? "rounded-xs bg-background-blue px-3 py-1.5 text-sm text-white"
                : "rounded-xs border border-border-5 bg-surface px-3 py-1.5 text-sm text-text-secondary"
            }
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        className={
          showDetailPanel
            ? "grid min-h-0 flex-1 gap-3 lg:grid-cols-12"
            : "flex min-h-0 flex-1"
        }
      >
        <div
          className={
            showDetailPanel
              ? "min-h-0 overflow-hidden rounded-xs border border-border-5 bg-surface lg:col-span-8"
              : "h-full min-h-0 w-full flex-1 overflow-hidden rounded-xs border border-border-5 bg-surface"
          }
        >
          <div className="h-full overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 border-b border-border-5 bg-surface uppercase text-xs text-text-muted">
                <tr>
                  <th className="px-4 py-2">Client</th>
                  <th className="px-4 py-2">Company</th>
                  <th className="px-4 py-2">Type</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {filteredRequests.length > 0 ? (
                  filteredRequests.map((request, index) => (
                    <tr
                      key={request.id}
                      onClick={() => setSelectedRequestId(request.id)}
                      className={`${index !== filteredRequests.length - 1 ? "border-b border-border-5" : ""} cursor-pointer hover:bg-background-5 ${selectedRequestId === request.id ? "bg-background-5" : ""}`}
                    >
                      <td className="px-4 py-3 font-medium text-text-primary">
                        {request.client_name ?? request.client_id}
                      </td>
                      <td className="px-4 py-3 text-text-secondary">
                        {truncateText(String(request.company ?? "-"))}
                      </td>
                      <td className="px-4 py-3 text-text-secondary">
                        <div className="flex flex-wrap gap-2">
                          {(request.display_type ?? request.agent_type ?? "")
                            .split(",")
                            .map((type) => type.trim())
                            .filter(Boolean)
                            .map((type, tagIndex) => (
                              <span
                                key={`${request.id}-${type}`}
                                className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs ${getTypeTagPill(tagIndex)}`}
                              >
                                {type}
                              </span>
                            ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs ${getStatusPill(request.status)}`}
                        >
                          {toLabel(request.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-text-secondary">
                        {formatDate(request.created_at)}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="px-4 py-6">
                      <PageEmptyState
                        title="No requests found"
                        message="Incoming client requests will appear in this queue."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {showDetailPanel && selectedRequest ? (
          <div className="self-start rounded-xs border border-border-5 bg-surface p-3 lg:col-span-4">
            <div className="flex items-center justify-between border-b border-border-5 pb-2">
              <p className="text-sm font-medium text-text-primary">
                Request Detail
              </p>
              <button
                onClick={() => setSelectedRequestId(null)}
                className="text-sm text-text-muted cursor-pointer"
                aria-label="Close request detail"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-2 py-2 text-sm">
              <div className="flex items-center justify-between border-b border-border-5 pb-1">
                <span className="text-text-muted">Client</span>
                <span className="text-text-secondary">
                  {selectedRequest.client_name ?? selectedRequest.client_id}
                </span>
              </div>
              <div className="flex items-center justify-between border-b border-border-5 pb-1">
                <span className="text-text-muted">Company</span>
                <span className="text-text-secondary">
                  {String(selectedRequest.company ?? "-")}
                </span>
              </div>
              <div className="flex items-start justify-between gap-3 border-b border-border-5 pb-1">
                <span className="text-text-muted">Agent Type</span>
                <div className="flex max-w-[70%] flex-wrap justify-end gap-2">
                  {(
                    selectedRequest.display_type ??
                    selectedRequest.agent_type ??
                    ""
                  )
                    .split(",")
                    .map((type) => type.trim())
                    .filter(Boolean)
                    .map((type, tagIndex) => (
                      <span
                        key={`${selectedRequest.id}-detail-${type}`}
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs ${getTypeTagPill(tagIndex)}`}
                      >
                        {type}
                      </span>
                    ))}
                  {!(
                    selectedRequest.display_type ??
                    selectedRequest.agent_type ??
                    ""
                  ).trim() ? (
                    <span className="text-text-secondary">-</span>
                  ) : null}
                </div>
              </div>
              <div className="flex items-center justify-between border-b border-border-5 pb-1">
                <span className="text-text-muted">Integrations</span>
                <span className="text-right text-text-secondary">
                  {(selectedRequest.suggested_agents ?? [])
                    .map((agent) => agent.label)
                    .join(", ") || "N/A"}
                </span>
              </div>
              <div className="flex items-center justify-between pb-1">
                <span className="text-text-muted">Submitted</span>
                <span className="text-text-secondary">
                  {formatDate(selectedRequest.created_at)}
                </span>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs text-text-muted">
                Note (optional)
              </label>
              <textarea
                rows={3}
                className="w-full rounded-xs border border-border-5 px-3 py-2  text-black text-sm outline-none"
                placeholder="Add a note..."
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <button
                onClick={onApprove}
                disabled={isApproving || isRejecting}
                className="inline-flex items-center justify-center gap-2 rounded-xs bg-background-blue px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isApproving ? (
                  <>
                    <span
                      className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                      aria-hidden
                    />
                    Approving...
                  </>
                ) : (
                  "✓ Approve"
                )}
              </button>
              <button
                onClick={onReject}
                disabled={isApproving || isRejecting}
                className="rounded-xs border cursor-pointer border-red-400/40 px-3 py-2 text-sm text-text-danger disabled:cursor-not-allowed disabled:opacity-70"
              >
                ⊗ Reject
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
