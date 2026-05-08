"use client";

import { useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { getClientActiveAgents, getClientConfig } from "@/lib/api";

const SEEN_BANNER_STORAGE_KEY = "client:new-agent-banner:seen";

const KNOWN_AGENTS = new Set([
  "a01_invoice",
  "a02_expense",
  "a03_admin",
  "a04_payment",
]);

interface NewAgent {
  agent: string;
  label: string;
  reason: string;
}

export default function NewAgentBanner() {
  const [newAgents, setNewAgents] = useState<NewAgent[]>([]);
  const [hiddenAgents, setHiddenAgents] = useState<Set<string>>(new Set());
  const [seenAgents, setSeenAgents] = useState<Set<string>>(new Set());
  const [isSeenLoaded, setIsSeenLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SEEN_BANNER_STORAGE_KEY);
      if (!raw) {
        setIsSeenLoaded(true);
        return;
      }
      const parsed = JSON.parse(raw) as string[];
      if (Array.isArray(parsed)) {
        setSeenAgents(
          new Set(parsed.filter((item) => typeof item === "string")),
        );
      }
    } catch {
    } finally {
      setIsSeenLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!isSeenLoaded) {
      return;
    }

    async function check() {
      try {
        const [activeRes, configRes] = await Promise.all([
          getClientActiveAgents(),
          getClientConfig(),
        ]);

        const suggestedAgents = (activeRes.active_agents as NewAgent[]) ?? [];
        const configuredIds: string[] = configRes.active_agents ?? [];

        const unseen = suggestedAgents.filter(
          (a) =>
            KNOWN_AGENTS.has(a.agent) &&
            !configuredIds.includes(a.agent) &&
            !seenAgents.has(a.agent),
        );

        setNewAgents(unseen);

        if (unseen.length > 0) {
          const updatedSeen = new Set(seenAgents);
          unseen.forEach((agent) => updatedSeen.add(agent.agent));
          setSeenAgents(updatedSeen);
          localStorage.setItem(
            SEEN_BANNER_STORAGE_KEY,
            JSON.stringify(Array.from(updatedSeen)),
          );
        }
      } catch {}
    }

    void check();
  }, [isSeenLoaded, seenAgents]);

  const visible = newAgents.filter((a) => !hiddenAgents.has(a.agent));
  if (!visible.length) return null;

  return (
    <div className="mb-4 space-y-2">
      {visible.map((agent) => (
        <div
          key={agent.agent}
          className="flex items-start justify-between gap-3 rounded-xs border border-emerald-400/40 bg-emerald-500/10 px-4 py-3"
        >
          <div className="flex items-start gap-3">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
            <div>
              <p className="text-sm font-semibold text-emerald-200">
                {agent.label} is now available for your account
              </p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {agent.reason}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() =>
              setHiddenAgents((prev) => new Set(prev).add(agent.agent))
            }
            className="shrink-0 text-emerald-300 hover:text-emerald-200"
            aria-label="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
