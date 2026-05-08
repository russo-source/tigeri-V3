"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Boxes, Cpu, ShieldCheck } from "lucide-react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";

const phaseStats = [
  {
    label: "Phase 1 — Core MVP",
    count: "8 agents",
    note: "Invoice, Expense, Admin, Staffing, Booking, Financial Reporting, Contract Management, Client Onboarding",
  },
  {
    label: "Phase 2 — Next Build",
    count: "6 agents",
    note: "Vendor, Payroll, CRM & Lead, Compliance & Audit, Support Ticket, Flight",
  },
  {
    label: "Phase 3 — Enterprise",
    count: "6 agents",
    note: "Security & Access, Data ETL, Email Triage, Procurement, HR & Staffing, Admin Workflow",
  },
];

const pillars = [
  {
    icon: Boxes,
    title: "20-agent catalog",
    body: "Each agent automates a specific operational function. Deploy individually or as a suite — per-agent subscription.",
  },
  {
    icon: Cpu,
    title: "MCP-first activation",
    body: "Sign in, connect your CRM via MCP (or API fallback). Tigeri reasons over your capabilities and ranks agents by ROI.",
  },
  {
    icon: ShieldCheck,
    title: "Audit-ready by default",
    body: "Every agent action emits an append-only audit record. Trust tiers gate actions for regulated industries.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <main className="flex-1">
        <section className="mx-auto max-w-6xl px-6 py-16 md:py-24">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="max-w-3xl"
          >
            <span className="inline-block rounded-full border border-border bg-surface px-3 py-1 font-mono text-xs uppercase tracking-wide text-text-secondary">
              Business automation, agent-by-agent
            </span>
            <h1 className="mt-5 text-4xl font-semibold tracking-tight md:text-5xl">
              Tigeri.ai replaces 0.5–2 FTEs per active agent at a fraction of
              headcount cost.
            </h1>
            <p className="mt-5 text-lg text-text-secondary">
              SaaS for SMEs running operational complexity across multiple
              venues, clients, crews, or locations. Conversational deployment,
              per-agent subscription, audit-ready logging, policy controls
              appropriate for regulated industries.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/sign-up"
                className="inline-flex items-center gap-2 rounded-md bg-navy px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark"
              >
                Provision a tenant <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/sign-in"
                className="inline-flex items-center gap-2 rounded-md border border-border px-5 py-2.5 text-sm font-medium text-text-primary transition-colors hover:bg-surface"
              >
                Sign in
              </Link>
            </div>
          </motion.div>
        </section>

        <section className="border-y border-border-5 bg-surface/30">
          <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-6 py-12 md:grid-cols-3">
            {pillars.map((p) => (
              <motion.div
                key={p.title}
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.3 }}
                className="rounded-md border border-border bg-surface p-5"
              >
                <p.icon className="h-6 w-6 text-navy" />
                <h3 className="mt-3 text-base font-semibold">{p.title}</h3>
                <p className="mt-2 text-sm text-text-secondary">{p.body}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="text-2xl font-semibold tracking-tight">
            20 agents across three phases
          </h2>
          <p className="mt-2 text-text-secondary">
            Build order follows the source-catalog priority. Phase 1 ships
            first; Phase 2 / 3 unlock as the foundation matures.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {phaseStats.map((p) => (
              <div
                key={p.label}
                className="rounded-md border border-border bg-surface p-5"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
                  {p.label}
                </p>
                <p className="mt-2 text-3xl font-semibold">{p.count}</p>
                <p className="mt-3 text-sm text-text-secondary">{p.note}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-border-5 bg-surface/30">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-10">
            <div>
              <h3 className="text-xl font-semibold">Try the Invoice Agent</h3>
              <p className="mt-1 text-sm text-text-secondary">
                Sign in with any tenant id and invoke the live LangGraph
                workflow against the deployed backend.
              </p>
            </div>
            <Link
              href="/sign-in"
              className="inline-flex items-center gap-2 rounded-md bg-navy px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-navy-dark"
            >
              Sign in <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>
      <GlobalFooter />
    </div>
  );
}
