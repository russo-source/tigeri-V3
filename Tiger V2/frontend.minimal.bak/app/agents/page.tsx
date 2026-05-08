"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AgentCard } from "@/lib/types";

export default function AgentsPage() {
  const [cards, setCards] = useState<AgentCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAgents()
      .then(setCards)
      .catch((e) => setError((e as Error).message));
  }, []);

  if (error)
    return (
      <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
    );
  if (!cards) return <div className="text-sm text-zinc-500">Loading agents…</div>;

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold text-zinc-900">Agent catalog</h1>
      <table className="w-full overflow-hidden rounded-lg border border-zinc-200 bg-white text-sm">
        <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Agent</th>
            <th className="px-3 py-2">Phase</th>
            <th className="px-3 py-2">Trust tier</th>
            <th className="px-3 py-2">Surfaces</th>
            <th className="px-3 py-2">ROI baseline</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((c) => (
            <tr key={c.agent_id} className="border-t border-zinc-200">
              <td className="px-3 py-2">{c.priority}</td>
              <td className="px-3 py-2 font-medium text-zinc-900">{c.name}</td>
              <td className="px-3 py-2 text-zinc-600">{c.phase}</td>
              <td className="px-3 py-2 text-zinc-600">{c.default_trust_tier}</td>
              <td className="px-3 py-2 text-zinc-600">
                {c.delivery_surfaces.join(", ")}
              </td>
              <td className="px-3 py-2 text-zinc-600">{c.roi_baseline}</td>
              <td className="px-3 py-2 text-zinc-600">{c.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
