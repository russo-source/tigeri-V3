"use client";

import { useEffect, useMemo, useState } from "react";
import { getAdminLogs } from "@/lib/api";
import { sanitizeSearchText } from "@/lib/input-validation";
import type { AdminLogEntry } from "@/lib/type";
import { formatDateAndTime } from "@/lib/helper";
import { AdminLogsSkeleton } from "@/components/ui/skeletons";

function getSeverityPill(severity: string) {
  const value = severity.toLowerCase();

  if (value === "info") {
    return "tag-info";
  }

  if (value === "warning") {
    return "tag-warning";
  }

  if (value === "error") {
    return "tag-error";
  }

  return "tag-info";
}

export default function AdminLogsPage() {
  const [logs, setLogs] = useState<AdminLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchValue, setSearchValue] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [fromTime, setFromTime] = useState("");
  const [toTime, setToTime] = useState("");
  const [activeFilter, setActiveFilter] = useState<
    "All" | "Info" | "Warning" | "Error" | "Action"
  >("All");

  useEffect(() => {
    async function loadData() {
      try {
        const logsData = await getAdminLogs();
        setLogs(logsData.logs);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load logs",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, []);

  const filteredLogs = useMemo(() => {
    const buildBoundaryDate = (
      date: string,
      time: string,
      fallback: "start" | "end",
    ) => {
      if (!date) return null;
      const resolvedTime = time || (fallback === "start" ? "00:00" : "23:59");
      const value = new Date(`${date}T${resolvedTime}:00`);
      return Number.isNaN(value.getTime()) ? null : value;
    };

    const fromBoundary = buildBoundaryDate(fromDate, fromTime, "start");
    const toBoundary = buildBoundaryDate(toDate, toTime, "end");

    return logs.filter((log) => {
      const severityMatch =
        activeFilter === "All" ||
        String(log.severity ?? "").toLowerCase() === activeFilter.toLowerCase();
      const searchMatch =
        String(log.message ?? "")
          .toLowerCase()
          .includes(searchValue.toLowerCase()) ||
        String(log.source ?? "")
          .toLowerCase()
          .includes(searchValue.toLowerCase());
      const logAt = new Date(String(log.at ?? ""));
      const hasValidLogTime = !Number.isNaN(logAt.getTime());

      const fromMatch =
        !fromBoundary ||
        !hasValidLogTime ||
        logAt.getTime() >= fromBoundary.getTime();
      const toMatch =
        !toBoundary ||
        !hasValidLogTime ||
        logAt.getTime() <= toBoundary.getTime();

      return severityMatch && searchMatch && fromMatch && toMatch;
    });
  }, [activeFilter, fromDate, fromTime, logs, searchValue, toDate, toTime]);

  if (isLoading) {
    return <AdminLogsSkeleton />;
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          System Logs
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          View system-wide events and errors
        </p>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="h-9 w-full max-w-[320px] rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none placeholder:text-text-muted"
          placeholder="Search logs..."
          maxLength={120}
          value={searchValue}
          onChange={(event) =>
            setSearchValue(sanitizeSearchText(event.target.value, 120))
          }
        />

        {["All", "Info", "Warning", "Error", "Action"].map((filter) => (
          <button
            key={filter}
            onClick={() => setActiveFilter(filter as typeof activeFilter)}
            className={
              activeFilter === filter
                ? "rounded-xs bg-background-blue px-3 py-1.5 text-sm text-white"
                : "rounded-xs border border-border-5 bg-surface px-3 py-1.5 text-sm text-text-secondary"
            }
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-text-muted">From</label>
        <input
          type="date"
          value={fromDate}
          onChange={(event) => setFromDate(event.target.value)}
          className="h-9 rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none"
          aria-label="Filter from date"
        />
        <input
          type="time"
          value={fromTime}
          onChange={(event) => setFromTime(event.target.value)}
          className="h-9 rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none"
          aria-label="Filter from time"
        />
        <label className="ml-2 text-sm text-text-muted">To</label>
        <input
          type="date"
          value={toDate}
          onChange={(event) => setToDate(event.target.value)}
          className="h-9 rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none"
          aria-label="Filter to date"
        />
        <input
          type="time"
          value={toTime}
          onChange={(event) => setToTime(event.target.value)}
          className="h-9 rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none"
          aria-label="Filter to time"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="h-full overflow-y-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10 border-b border-border-5 bg-surface uppercase text-xs text-text-muted">
              <tr>
                <th className="px-4 py-2">Time</th>
                <th className="px-4 py-2">Severity</th>
                <th className="px-4 py-2">Message</th>
                <th className="px-4 py-2">Source</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.length > 0 ? (
                filteredLogs.map((log, index) => (
                  <tr
                    key={`${log.at ?? ""}-${log.message ?? ""}-${index}`}
                    className={
                      index !== filteredLogs.length - 1
                        ? "border-b border-border-5"
                        : ""
                    }
                  >
                    <td className="px-4 py-3 text-text-secondary">
                      {formatDateAndTime(log.at as string) ?? "-"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs ${getSeverityPill(String(log.severity ?? "info"))}`}
                      >
                        {String(log.severity ?? "Info")}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-text-primary">
                      {String(log.message ?? "-")}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {String(log.source ?? "-")}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-6 text-center text-sm text-text-muted"
                  >
                    No logs.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
