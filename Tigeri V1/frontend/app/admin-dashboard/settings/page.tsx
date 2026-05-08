"use client";

import { useEffect, useState } from "react";
import {
  getAdminClientIntegrations,
  getAdminClients,
  getAdminToggles,
  updateAdminToggles,
} from "@/lib/api";
import type { AdminClient, ClientIntegration } from "@/lib/type";
import CustomSelect from "@/components/ui/custom-select";
import { AdminSettingsSkeleton } from "@/components/ui/skeletons";
import { Check, X } from "lucide-react";

export default function AdminSettingsPage() {
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [clientIntegrations, setClientIntegrations] = useState<
    ClientIntegration[]
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [maintenanceUntil, setMaintenanceUntil] = useState<string | null>(null);
  const [maintenanceMinutes, setMaintenanceMinutes] = useState(60);

  const onToggleMaintenance = async () => {
    try {
      const updated = await updateAdminToggles({
        maintenance_mode: !maintenanceMode,
        maintenance_minutes: !maintenanceMode ? maintenanceMinutes : undefined,
      });
      setMaintenanceMode(updated.maintenance_mode);
      setMaintenanceUntil(updated.maintenance_until ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Toggle failed");
    }
  };
  const onExtend = async () => {
    try {
      const updated = await updateAdminToggles({
        maintenance_mode: true,
        maintenance_minutes: maintenanceMinutes,
      });
      setMaintenanceUntil(updated.maintenance_until ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extend failed");
    }
  };
  useEffect(() => {
    async function loadToggles() {
      try {
        const t = await getAdminToggles();
        setMaintenanceMode(t.maintenance_mode);
      } catch {}
    }
    void loadToggles();
  }, []);

  useEffect(() => {
    async function loadData() {
      try {
        const clientsResponse = await getAdminClients();

        setClients(clientsResponse.clients);

        const firstClientId = clientsResponse.clients[0]?.id ?? "";
        setSelectedClientId(firstClientId);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load settings",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, []);

  useEffect(() => {
    async function loadClientIntegrations() {
      if (!selectedClientId) {
        setClientIntegrations([]);
        return;
      }

      try {
        const integrationsResponse =
          await getAdminClientIntegrations(selectedClientId);
        setClientIntegrations(integrationsResponse.integrations);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load client integration settings",
        );
      }
    }

    void loadClientIntegrations();
  }, [selectedClientId]);

  if (isLoading) {
    return <AdminSettingsSkeleton />;
  }

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Settings</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Manage providers and per-client integration visibility
        </p>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <p className="text-sm font-medium text-text-primary">
          Client Integration Inspector
        </p>
        <p className="mt-1 text-xs text-text-muted">
          Uses admin integration endpoints for the selected client
        </p>

        <div className="mt-3">
          <label className="mb-1 block text-sm text-text-secondary">
            Client
          </label>
          <CustomSelect
            value={selectedClientId}
            onChange={(event) => setSelectedClientId(event.target.value)}
            className="h-10 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary"
          >
            {clients.map((client) => (
              <option key={client.id} value={client.id}>
                {String(client.name ?? client.email)} ({client.company})
              </option>
            ))}
          </CustomSelect>
        </div>

        <div className="mt-4 space-y-2">
          {clientIntegrations.map((integration) => (
            <div
              key={integration.provider}
              className="rounded-xs border border-border-5 bg-background-5 px-3 py-2 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-text-primary">
                  {integration.label}
                </span>
                <span
                  className={`ml-6 rounded-full px-4 py-1 text-xs ${integration.connected ? "tag-connected" : "tag-disconnected"}`}
                >
                  {integration.connected ? "Connected" : "Disconnected"}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <p className="text-sm font-medium text-text-primary">System Toggles</p>
        <div className="mt-3 rounded-xs border border-border-5 bg-background-5 p-3 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-text-primary">Maintenance mode</p>
              <p className="text-xs text-text-muted">
                Disables all agent routing
              </p>
              {maintenanceMode && maintenanceUntil ? (
                <p className="tag-warning mt-0.5 inline-flex rounded-full px-2 py-0.5 text-xs">
                  Until {new Date(maintenanceUntil).toLocaleString()}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => {
                const message = maintenanceMode
                  ? "Disabling maintenance mode will re-enable agent routing. Continue?"
                  : "Enabling maintenance mode will disable all agent routing for the specified duration. Continue?";
                if (window.confirm(message)) {
                  void onToggleMaintenance();
                }
              }}
              className={`relative inline-flex h-8 w-14 items-center rounded-full transition-colors ${maintenanceMode ? "bg-background-blue" : "bg-border-5"}`}
              aria-label={`Maintenance mode ${maintenanceMode ? "enabled" : "disabled"}`}
              aria-pressed={maintenanceMode}
            >
              <span
                className={`relative inline-flex h-6 w-6 transform items-center justify-center rounded-full bg-background shadow transition-transform ${maintenanceMode ? "translate-x-7" : "translate-x-1"}`}
              >
                <Check
                  className={`absolute h-3.5 w-3.5 text-text-primary transition-all duration-200 ${maintenanceMode ? "scale-100 opacity-100" : "scale-0 opacity-0"}`}
                />
                <X
                  className={`absolute h-3.5 w-3.5 text-text-primary transition-all duration-200 ${maintenanceMode ? "scale-0 opacity-0" : "scale-100 opacity-100"}`}
                />
              </span>
            </button>
          </div>

          {maintenanceMode && (
            <div className=" text-black flex items-center gap-2 pt-2 border-t border-border-5">
              <input
                type="number"
                min="1"
                value={maintenanceMinutes}
                onChange={(e) =>
                  setMaintenanceMinutes(parseInt(e.target.value))
                }
                className="h-8 w-16 rounded border border-border-5 px-2 text-xs"
              />
              <span className="text-xs text-text-muted">minutes</span>
              <button
                onClick={() => void onExtend()}
                className="ml-auto rounded-lg bg-background-blue px-3 py-1.5 text-xs text-white"
              >
                Extend
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
