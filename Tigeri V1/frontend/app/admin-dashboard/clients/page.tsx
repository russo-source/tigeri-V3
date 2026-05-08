"use client";

import { useEffect, useMemo, useState } from "react";
import { getAdminClients, setAdminClientStatus } from "@/lib/api";
import { sanitizeSearchText } from "@/lib/input-validation";
import type { AdminClient } from "@/lib/type";
import { formatDate, truncateText } from "@/lib/helper";
import { AdminClientsSkeleton } from "@/components/ui/skeletons";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-states";
import { X } from "lucide-react";

function getPaymentPill(active: boolean) {
  return active ? "tag-paid" : "tag-unpaid";
}

function getClientStatusPill(active: boolean) {
  return active ? "tag-active" : "tag-suspended";
}

function getAgentTagPill(index: number) {
  const palettes = [
    "tag-type-1",
    "tag-type-2",
    "tag-type-3",
    "tag-type-4",
  ] as const;

  return palettes[index % palettes.length];
}

export default function AdminClientsPage() {
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchValue, setSearchValue] = useState("");
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const response = await getAdminClients();
        setClients(response.clients);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load clients",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, []);

  const filteredClients = useMemo(() => {
    const query = searchValue.trim().toLowerCase();

    if (!query) {
      return clients;
    }

    return clients.filter(
      (client) =>
        String(client.name ?? "")
          .toLowerCase()
          .includes(query) ||
        String(client.company ?? "")
          .toLowerCase()
          .includes(query) ||
        String(client.email ?? "")
          .toLowerCase()
          .includes(query),
    );
  }, [clients, searchValue]);

  const selectedClient = selectedClientId
    ? (clients.find((client) => client.id === selectedClientId) ?? null)
    : null;

  const showDetailPanel = Boolean(selectedClient);

  const handleCopyEmail = async (email: string) => {
    if (!email || email === "-") {
      return;
    }

    try {
      await navigator.clipboard.writeText(email);
    } catch {
      setError("Failed to copy email");
    }
  };

  const onToggleStatus = async (client: AdminClient) => {
    try {
      await setAdminClientStatus(client.id, !client.active);
      const refreshed = await getAdminClients();
      setClients(refreshed.clients);
      setSelectedClientId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Status update failed");
    }
  };
  if (isLoading) {
    return <AdminClientsSkeleton />;
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Clients</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Manage client accounts and activation status
        </p>
      </div>

      {error ? <PageErrorState message={error} /> : null}

      <div className="flex items-center gap-2">
        <input
          className="h-9 w-full max-w-[320px] rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none placeholder:text-text-muted"
          placeholder="Search clients..."
          aria-label="Search clients"
          maxLength={100}
          value={searchValue}
          onChange={(event) =>
            setSearchValue(sanitizeSearchText(event.target.value, 100))
          }
        />
        <p className="text-xs text-text-muted">{clients.length} clients</p>
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
              <thead className="sticky top-0 z-10 border-b border-border-5 bg-surface text-xs uppercase text-text-muted">
                <tr>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">Company</th>
                  {/* <th className="px-4 py-2">Email</th> */}
                  <th className="px-4 py-2">Agents</th>
                  <th className="px-4 py-2">Payment</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Joined</th>
                </tr>
              </thead>
              <tbody>
                {filteredClients.length > 0 ? (
                  filteredClients.map((client, index) => (
                    <tr
                      key={client.id}
                      onClick={() => setSelectedClientId(client.id)}
                      className={`${index !== filteredClients.length - 1 ? "border-b border-border-5" : ""} cursor-pointer hover:bg-background-5 ${selectedClientId === client.id ? "bg-background-5" : ""}`}
                    >
                      <td className="px-4 py-3 font-medium text-text-primary">
                        {String(client.name ?? "Unknown")}
                      </td>
                      <td className="px-4 py-3 text-text-secondary">
                        {truncateText(String(client.company ?? "-"))}
                      </td>
                      {/* <td className="px-4 py-3 text-text-secondary">
                        {truncateText(String(client.email ?? "-"))}
                      </td> */}
                      <td className="px-4 py-3 text-text-secondary">
                        <div
                          className={
                            showDetailPanel
                              ? "grid grid-cols-1 gap-2"
                              : "flex flex-wrap gap-2"
                          }
                        >
                          {String(client.agents_label ?? "")
                            .split(",")
                            .map((agent) => agent.trim())
                            .filter(Boolean)
                            .map((agent, tagIndex) => (
                              <span
                                key={`${client.id}-${agent}`}
                                className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs ${getAgentTagPill(tagIndex)}`}
                              >
                                {agent}
                              </span>
                            ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs ${getPaymentPill(Boolean(client.active))}`}
                        >
                          {client.active ? "Paid" : "Unpaid"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs ${getClientStatusPill(Boolean(client.active))}`}
                        >
                          {client.active ? "Active" : "Suspended"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-text-secondary">
                        {formatDate(String(client.created_at ?? ""))}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="px-4 py-6">
                      <PageEmptyState
                        title="No clients found"
                        message="New clients will appear here once onboarded."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {showDetailPanel && selectedClient ? (
          <div className="self-start rounded-xs border border-border-5 bg-surface p-3 lg:col-span-4">
            <div className="flex items-center justify-between border-b border-border-5 pb-2">
              <p className="text-sm font-medium text-text-primary">
                Client Detail
              </p>
              <button
                onClick={() => setSelectedClientId(null)}
                className="text-xs text-text-muted cursor-pointer"
                aria-label="Close client detail"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex items-center gap-2 py-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-background-blue text-[10px] text-white">
                {selectedClient.name
                  ? String(selectedClient.name)
                      .split(" ")
                      .map((part) => part[0])
                      .slice(0, 2)
                      .join("")
                      .toUpperCase()
                  : "CL"}
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">
                  {String(selectedClient.name ?? "Unknown")}
                </p>
                <p className="text-xs text-text-secondary">
                  {String(selectedClient.company ?? "-")}
                </p>
              </div>
            </div>

            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between border-b border-border-5 pb-2">
                <span className="text-text-muted">Email</span>
                <span className="flex max-w-[70%] items-center justify-end gap-2 text-right text-text-secondary">
                  <button
                    type="button"
                    onClick={() =>
                      void handleCopyEmail(String(selectedClient.email ?? "-"))
                    }
                    className="inline-flex h-5 w-5 items-center justify-center rounded-xs border border-border-5 text-text-muted hover:text-text-primary"
                    aria-label="Copy email"
                    title="Copy email"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className="h-3.5 w-3.5"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                  </button>
                  <span className="break-all">
                    {String(selectedClient.email ?? "-")}
                  </span>
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-border-5 pb-2">
                <span className="text-text-muted">Company</span>
                <span className="text-text-secondary">
                  {String(selectedClient.company ?? "-")}
                </span>
              </div>
              <div className="flex items-start justify-between gap-3 border-b border-border-5 pb-1">
                <span className="text-text-muted">Agents</span>
                <div className="flex max-w-[70%] flex-wrap justify-end gap-2">
                  {String(selectedClient.agents_label ?? "")
                    .split(",")
                    .map((agent) => agent.trim())
                    .filter(Boolean)
                    .map((agent, tagIndex) => (
                      <span
                        key={`${selectedClient.id}-detail-${agent}`}
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs ${getAgentTagPill(tagIndex)}`}
                      >
                        {agent}
                      </span>
                    ))}
                  {!String(selectedClient.agents_label ?? "").trim() ? (
                    <span className="text-text-secondary">-</span>
                  ) : null}
                </div>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-border-5 pb-1">
                <span className="text-text-muted">Payment</span>
                <span
                  className={`rounded-full px-2.5 py-1 text-xs ${getPaymentPill(Boolean(selectedClient.active))}`}
                >
                  {selectedClient.active ? "Paid" : "Unpaid"}
                </span>
              </div>
              <div className="flex items-center justify-between border-b border-border-5 pb-1">
                <span className="text-text-muted">Status</span>
                <span
                  className={`rounded-full px-2.5 py-1 text-xs ${getClientStatusPill(Boolean(selectedClient.active))}`}
                >
                  {selectedClient.active ? "Active" : "Suspended"}
                </span>
              </div>
              <div className="flex items-center justify-between pb-1">
                <span className="text-text-muted">Joined</span>
                <span className="text-text-secondary">
                  {formatDate(selectedClient.created_at ?? "-")}
                </span>
              </div>
            </div>

            <button
              onClick={() => void onToggleStatus(selectedClient)}
              className={`mt-3 w-full rounded-xs px-3 py-2 text-sm ${selectedClient.active === false ? "tag-active" : "tag-suspended"}`}
            >
              {selectedClient.active === false ? "↗ Activate" : "↘ Suspend"}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
