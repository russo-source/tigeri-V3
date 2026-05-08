"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type {
  ActivationObjectivesResponse,
  ActivationStartResponse,
  Recommendation,
} from "@/lib/types";

type Step = "connect" | "objectives" | "review" | "deployed";

export default function ActivationPage() {
  const [step, setStep] = useState<Step>("connect");
  const [error, setError] = useState<string | null>(null);
  const [start, setStart] = useState<ActivationStartResponse | null>(null);
  const [recommendations, setRecommendations] =
    useState<ActivationObjectivesResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function connect(form: FormData) {
    setError(null);
    try {
      const res = await api.startActivation({
        source_system: String(form.get("source_system") ?? ""),
        api_base_url: String(form.get("api_base_url") ?? "") || null,
        mcp_endpoint: String(form.get("mcp_endpoint") ?? "") || null,
      });
      setStart(res);
      if (res.state === "S4_OBJECTIVE_INTAKE") setStep("objectives");
      else setError(`Activation reached failure state ${res.state}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submitObjectives(form: FormData) {
    setError(null);
    try {
      const res = await api.submitObjectives({
        industry: String(form.get("industry") ?? ""),
        employee_count: Number(form.get("employee_count") ?? 0),
        venues_or_locations: Number(form.get("venues_or_locations") ?? 0),
        regulated: form.get("regulated") === "on",
        objectives: [
          { objective: String(form.get("objective") ?? ""), priority: "HIGH" },
        ],
      });
      setRecommendations(res);
      if (res.state === "S6_RECOMMENDATION_REVIEW") setStep("review");
      else setError(`Objectives reached failure state ${res.state}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function deployNow() {
    setError(null);
    try {
      await api.deployAgents([...selected]);
      setStep("deployed");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggle(agentId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Activation</h1>
      <ol className="flex gap-4 text-sm text-zinc-500">
        <Pill active={step === "connect"}>1. Connect CRM</Pill>
        <Pill active={step === "objectives"}>2. Objectives</Pill>
        <Pill active={step === "review"}>3. Review</Pill>
        <Pill active={step === "deployed"}>4. Active</Pill>
      </ol>
      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {step === "connect" && (
        <form
          className="space-y-3 rounded-lg border border-zinc-200 bg-white p-5"
          action={(formData) => {
            void connect(formData);
          }}
        >
          <Field name="source_system" label="Source system" defaultValue="legacy_crm" />
          <Field name="mcp_endpoint" label="MCP endpoint (optional)" placeholder="https://mcp.example.com" />
          <Field name="api_base_url" label="API base URL" placeholder="https://api.example.com" />
          <p className="text-xs text-zinc-500">
            Tigeri uses MCP if the CRM advertises it, else falls back to API.
          </p>
          <button className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white">
            Discover capabilities
          </button>
        </form>
      )}

      {step === "objectives" && (
        <form
          className="space-y-3 rounded-lg border border-zinc-200 bg-white p-5"
          action={(formData) => {
            void submitObjectives(formData);
          }}
        >
          <Field name="industry" label="Industry" defaultValue="logistics" />
          <Field name="employee_count" type="number" label="Employee count" defaultValue="50" />
          <Field name="venues_or_locations" type="number" label="Venues / locations" defaultValue="2" />
          <label className="flex items-center gap-2 text-sm text-zinc-800">
            <input type="checkbox" name="regulated" defaultChecked /> Regulated industry
          </label>
          <Field
            name="objective"
            label="Top objective"
            defaultValue="automate vendor invoice processing"
          />
          <button className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white">
            Get recommendations
          </button>
          {start?.inventory && (
            <p className="text-xs text-zinc-500">
              Discovered objects:{" "}
              <code>{start.inventory.discovered_objects.join(", ") || "(none)"}</code>
            </p>
          )}
        </form>
      )}

      {step === "review" && recommendations?.recommendations && (
        <div className="space-y-3 rounded-lg border border-zinc-200 bg-white p-5">
          <div className="text-sm font-medium text-zinc-900">
            Ranked recommendations
          </div>
          <ul className="space-y-2">
            {recommendations.recommendations.ranked_recommendations.map(
              (r: Recommendation) => (
                <li
                  key={r.agent_id}
                  className="flex items-start gap-3 rounded-md border border-zinc-200 p-3"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.agent_id)}
                    onChange={() => toggle(r.agent_id)}
                    className="mt-1"
                  />
                  <div>
                    <div className="text-sm font-medium text-zinc-900">
                      #{r.rank} {r.agent_id} (score {r.match_score})
                    </div>
                    <div className="text-xs text-zinc-600">{r.rationale}</div>
                    <div className="mt-1 text-xs text-zinc-500">
                      Projected ROI: {r.projected_roi}
                    </div>
                  </div>
                </li>
              ),
            )}
          </ul>
          <button
            onClick={deployNow}
            disabled={selected.size === 0}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:bg-zinc-300"
          >
            Deploy {selected.size} agent{selected.size === 1 ? "" : "s"}
          </button>
        </div>
      )}

      {step === "deployed" && (
        <div className="rounded-md bg-green-50 p-4 text-sm text-green-800">
          Agents are active. Visit the Invoice inbox or the Audit log to see them in
          action.
        </div>
      )}
    </section>
  );
}

function Pill({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <li
      className={
        "rounded-full px-3 py-1 " +
        (active ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700")
      }
    >
      {children}
    </li>
  );
}

function Field({
  name,
  label,
  defaultValue,
  placeholder,
  type = "text",
}: {
  name: string;
  label: string;
  defaultValue?: string;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-sm font-medium text-zinc-800">
      {label}
      <input
        name={name}
        type={type}
        defaultValue={defaultValue}
        placeholder={placeholder}
        className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm"
      />
    </label>
  );
}
