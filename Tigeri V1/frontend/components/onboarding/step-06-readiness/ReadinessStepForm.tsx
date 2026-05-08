"use client";

import { useEffect, useState } from "react";
import { ChevronUp, Loader2 } from "lucide-react";
import { previewOnboarding, type OnboardingPreviewResponse } from "@/lib/api";

type SuggestedAgent = OnboardingPreviewResponse["suggested_agents"][number];

interface Props {
  steps: unknown[];
}

const AGENT_META: Record<
  string,
  { price: string; tags: string[]; integrations: string }
> = {
  a01_invoice: {
    price: "$499",
    tags: [
      "Invoice Generation",
      "Status Tracking",
      "Payment Reminders",
      "AP Processing",
    ],
    integrations: "Xero, QuickBooks, NetSuite, M365 Business Central",
  },
  a02_expense: {
    price: "$499",
    tags: [
      "Receipt Capture",
      "Data Extraction",
      "GL Coding",
      "Approval Routing",
    ],
    integrations: "Email, WhatsApp, Xero, QuickBooks",
  },
  a03_admin: {
    price: "$499",
    tags: ["Document Management", "Calendar Coordination", "Client Onboarding"],
    integrations: "Email, calendar platforms, document storage",
  },
  a04_payment: {
    price: "$499",
    tags: [
      "Payment Tracking",
      "Invoice Matching",
      "Mismatch Handling",
      "Cashflow Reporting",
    ],
    integrations: "Bank feeds, payment gateways, Xero, QuickBooks",
  },
};

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-background-5 text-text-secondary",
};

export default function ReadinessStepForm({ steps }: Props) {
  const [agents, setAgents] = useState<SuggestedAgent[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [profile, setProfile] = useState<
    OnboardingPreviewResponse["parsed_profile"] | null
  >(null);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );

  useEffect(() => {
    const hasData = steps.some((s: unknown) => {
      const step = s as {
        forms?: { fields?: Record<string, unknown> }[];
      } | null;
      return step?.forms?.some((f) =>
        Object.values(f?.fields ?? {}).some(
          (v) => v !== "" && v !== null && v !== undefined,
        ),
      );
    });

    if (!hasData) return;

    let cancelled = false;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");

    previewOnboarding(steps)
      .then((res) => {
        if (cancelled) return;
        setAgents(res.suggested_agents);
        setPlatforms(res.integration_platforms ?? []);
        setProfile(res.parsed_profile);
        setStatus("done");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [steps]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 rounded-xs bg-background-blue p-4 text-white">
        <p className="w-12 text-base">06.A</p>
        <div className="flex-1">
          <p className="text-base">Review &amp; Submit</p>
        </div>
        <span className="text-base text-white/80">
          {status === "done" ? "Complete" : "Analysing..."}
        </span>
        <span className="ml-4 text-white/80" aria-hidden>
          <ChevronUp size={20} />
        </span>
      </div>

      {profile && (
        <div className="space-y-2">
          {[
            { label: "Industry", value: profile.industry || "—" },
            {
              label: "Integrations",
              value: profile.integrations || "None detected",
            },
            {
              label: "Compliance",
              value: profile.compliance || "None selected",
            },
          ].map((item) => (
            <div
              key={item.label}
              className="flex items-center justify-between rounded-xs border border-border-5 bg-background-5 px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <span className="inline-block h-3 w-3 rounded-full bg-border-10" />
                <p className="text-base text-text-primary">{item.label}</p>
              </div>
              <p className="max-w-xs truncate text-right text-base text-text-secondary">
                {item.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {platforms.length > 0 && (
        <div className="rounded-xs border border-border-5 bg-surface px-4 py-3">
          <p className="mb-2 text-sm font-semibold text-text-primary">
            Detected Integration Platforms
          </p>
          <div className="flex flex-wrap gap-2">
            {platforms.map((p) => (
              <span
                key={p}
                className="rounded-xs border border-border-5 bg-background-5 px-2.5 py-1 text-sm text-text-secondary"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-sm text-text-secondary">
        You can always update these settings later.
      </p>

      {(status === "idle" || status === "loading") && (
        <div className="flex items-center gap-3 rounded-xs border border-border-5 bg-surface px-4 py-6">
          <Loader2 className="h-5 w-5 animate-spin text-background-blue" />
          <p className="text-base text-text-secondary">
            Analysing your profile to recommend agents...
          </p>
        </div>
      )}

      {status === "error" && (
        <p className="rounded-xs border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Could not load recommendations. You can still submit — our team will
          review your profile and configure the right agents.
        </p>
      )}

      {status === "done" && agents.length === 0 && (
        <p className="text-sm text-text-secondary">
          No specific agents matched your profile. Our team will review and
          recommend the best fit after submission.
        </p>
      )}

      {status === "done" && agents.length > 0 && (
        <>
          <p className="text-sm text-text-primary">
            Based on your profile, we recommend the following agents:
          </p>

          <div className="space-y-2">
            {agents.map((agent) => {
              const meta = AGENT_META[agent.agent];
              if (!meta) return null;

              return (
                <article
                  key={agent.agent}
                  className="rounded-xs border border-border-5 bg-surface px-4 py-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h3 className="text-xl font-semibold text-text-primary">
                        {agent.label}
                      </h3>
                      <p className="mt-0.5 text-sm text-text-secondary">
                        {agent.reason}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xl text-text-primary">{meta.price}</p>
                      <p className="mt-1 text-sm text-text-secondary">
                        est. /month
                      </p>
                    </div>
                  </div>

                  <p className="mt-1 text-sm text-text-secondary">
                    <span className="text-text-primary">Integrations:</span>{" "}
                    {meta.integrations}
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {meta.tags.map((tag: string) => (
                      <span
                        key={tag}
                        className="rounded-xs border border-border-5 bg-background-5 px-2.5 py-1 text-sm text-text-secondary"
                      >
                        {tag}
                      </span>
                    ))}
                    <span
                      className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                        PRIORITY_STYLES[agent.priority] ?? PRIORITY_STYLES.low
                      }`}
                    >
                      {agent.priority} priority
                    </span>
                  </div>

                  <div className="mt-2 flex justify-end">
                    <button
                      type="button"
                      className="rounded-full bg-background-blue px-3 py-1 text-xs text-white"
                    >
                      7-Day Free Trial
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
