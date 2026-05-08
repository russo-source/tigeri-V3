"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ActivationObjectivesResponse,
  ActivationStartResponse,
  Recommendation,
} from "@/lib/type";

type Step = "connect" | "objectives" | "review" | "deployed";

export default function ActivationPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("connect");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState<ActivationStartResponse | null>(null);
  const [recs, setRecs] = useState<ActivationObjectivesResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function connect(form: FormData) {
    setError(null);
    setBusy(true);
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
    } finally {
      setBusy(false);
    }
  }

  async function submitObjectives(form: FormData) {
    setError(null);
    setBusy(true);
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
      setRecs(res);
      // Pre-select the top recommendation
      const top = res.recommendations?.ranked_recommendations?.[0];
      if (top) setSelected(new Set([top.agent_id]));
      if (res.state === "S6_RECOMMENDATION_REVIEW") setStep("review");
      else setError(`Reasoning reached failure state ${res.state}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deploy() {
    setError(null);
    setBusy(true);
    try {
      await api.deployAgents([...selected]);
      setStep("deployed");
      setTimeout(() => router.push("/client-dashboard/home"), 1200);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
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
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Activation</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Connect your CRM, share your objectives, accept the agents Tigeri
          recommends.
        </p>
      </header>

      <ol className="flex flex-wrap gap-2 text-xs">
        <Pill active={step === "connect"} done={step !== "connect"}>1. Connect</Pill>
        <Pill active={step === "objectives"} done={step === "review" || step === "deployed"}>
          2. Objectives
        </Pill>
        <Pill active={step === "review"} done={step === "deployed"}>3. Review</Pill>
        <Pill active={step === "deployed"} done={false}>4. Active</Pill>
      </ol>

      {error ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
          {error}
        </div>
      ) : null}

      {step === "connect" && (
        <Card>
          <form
            className="space-y-4"
            action={(formData) => {
              void connect(formData);
            }}
          >
            <Field name="source_system" label="Source system" defaultValue="legacy_crm" />
            <Field
              name="mcp_endpoint"
              label="MCP endpoint (optional)"
              placeholder="https://mcp.example.com"
            />
            <Field
              name="api_base_url"
              label="API base URL"
              placeholder="https://api.example.com"
            />
            <p className="text-xs text-text-muted">
              Tigeri uses MCP if the CRM advertises it, else falls back to API.
            </p>
            <button
              disabled={busy}
              className="rounded-md bg-navy px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
            >
              {busy ? "Discovering…" : "Discover capabilities"}
            </button>
          </form>
        </Card>
      )}

      {step === "objectives" && (
        <Card>
          <form
            className="space-y-4"
            action={(formData) => {
              void submitObjectives(formData);
            }}
          >
            <Field name="industry" label="Industry" defaultValue="logistics" />
            <Field
              name="employee_count"
              type="number"
              label="Employee count"
              defaultValue="50"
            />
            <Field
              name="venues_or_locations"
              type="number"
              label="Venues / locations"
              defaultValue="2"
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="regulated" defaultChecked /> Regulated
              industry
            </label>
            <Field
              name="objective"
              label="Top objective"
              defaultValue="automate vendor invoice processing"
            />
            {start?.inventory ? (
              <p className="text-xs text-text-muted">
                Capability inventory:{" "}
                <code>
                  {start.inventory.discovered_objects.join(", ") || "(empty)"}
                </code>
              </p>
            ) : null}
            <button
              disabled={busy}
              className="rounded-md bg-navy px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
            >
              {busy ? "Reasoning…" : "Get recommendations"}
            </button>
          </form>
        </Card>
      )}

      {step === "review" && recs?.recommendations && (
        <Card>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
            Ranked recommendations
          </h2>
          <ul className="mt-3 space-y-2">
            {recs.recommendations.ranked_recommendations.map(
              (r: Recommendation) => (
                <li
                  key={r.agent_id}
                  className="flex items-start gap-3 rounded-md border border-border p-3"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.agent_id)}
                    onChange={() => toggle(r.agent_id)}
                    className="mt-1"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">
                      #{r.rank} {r.agent_id} · score {r.match_score}
                    </div>
                    <p className="mt-1 text-xs text-text-secondary">
                      {r.rationale}
                    </p>
                    <p className="mt-1 text-xs text-text-muted">
                      Projected ROI: {r.projected_roi}
                    </p>
                  </div>
                </li>
              ),
            )}
          </ul>
          <button
            onClick={deploy}
            disabled={busy || selected.size === 0}
            className="mt-4 rounded-md bg-navy px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
          >
            {busy
              ? "Deploying…"
              : `Deploy ${selected.size} agent${selected.size === 1 ? "" : "s"}`}
          </button>
        </Card>
      )}

      {step === "deployed" && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-md border border-border bg-surface p-6 text-sm text-text-primary"
        >
          <div className="flex items-center gap-2 text-success">
            <CheckCircle2 className="h-5 w-5" />
            <span className="font-medium">Agents are active.</span>
          </div>
          <p className="mt-2 text-text-secondary">
            Heading to your agent catalog…
          </p>
        </motion.div>
      )}
    </div>
  );
}

function Pill({
  active,
  done,
  children,
}: {
  active: boolean;
  done: boolean;
  children: React.ReactNode;
}) {
  const cls = active
    ? "bg-navy text-white border border-navy-darker"
    : done
      ? "bg-surface-blue text-success border border-success/40"
      : "bg-surface text-text-muted border border-border";
  return (
    <li className={`rounded-full px-3 py-1 font-mono text-[11px] uppercase tracking-wide ${cls}`}>
      {children}
    </li>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-surface p-5">
      {children}
    </section>
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
    <label className="block text-sm font-medium">
      {label}
      <input
        name={name}
        type={type}
        defaultValue={defaultValue}
        placeholder={placeholder}
        className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
      />
    </label>
  );
}
