import Link from "next/link";

const CORE_AGENTS = [
  {
    id: "A01",
    name: "Invoice Agent",
    priority: "Highest Priority",
    function:
      "Core cashflow engine for all verticals with invoice lifecycle automation.",
    capabilities: [
      "Generates and sends invoices to end-clients",
      "Tracks invoice status (paid, unpaid, overdue)",
      "Sends automated payment reminders",
      "Processes inbound accounts payable (AP)",
    ],
    integrations:
      "Xero, QuickBooks, NetSuite, M365 Business Central (as applicable)",
    acceptance:
      "Successfully generates, sends, and tracks test invoices during UAT with 99%+ data accuracy. Human review fallback process documented.",
  },
  {
    id: "A02",
    name: "Expense Agent",
    priority: "Priority 2",
    function: "End-to-end expense management with extraction and approvals.",
    capabilities: [
      "Captures receipts via email and WhatsApp",
      "AI-based data extraction from receipts",
      "General Ledger (GL) coding and categorisation",
      "Approval routing workflow",
      "Posts approved expenses to accounting platforms",
    ],
    integrations: "Email, WhatsApp, Xero, QuickBooks",
    acceptance:
      "Successfully captures, extracts, codes, and posts test expense entries during UAT with 99%+ extraction accuracy. Human review fallback process documented.",
  },
  {
    id: "A03",
    name: "Admin Agent",
    priority: "Priority 3",
    function: "Foundational coordination and glue layer across operations.",
    capabilities: [
      "Document management and retrieval",
      "Scheduling and calendar coordination",
      "Client onboarding workflows",
      "Routine correspondence handling",
    ],
    integrations: "Email, calendar platforms, document storage",
    acceptance:
      "Successfully executes defined admin workflows during UAT with documented error handling for edge cases.",
  },
  {
    id: "A04",
    name: "Payment & Reconciliation Agent",
    priority: "MVP Priority 4",
    function: "Real-time payment tracking and reconciliation across channels.",
    capabilities: [
      "Tracks incoming payments across bank feeds, payment gateways, WhatsApp, email, and manual uploads",
      "Auto-matches payments to open invoices from A01 (target 99%+ accuracy)",
      "Handles partial payments, over-payments, and flags mismatches for human review",
      "Sends automated payment reminders at 7, 14, and 21-day intervals",
      "Posts reconciled payments to accounting platforms",
      "Generates weekly cash-flow and ageing reports",
    ],
    integrations:
      "Bank feeds, payment gateways, Xero, QuickBooks, NetSuite, M365 Business Central",
    acceptance:
      "Successfully reconciles test transactions during UAT with 99%+ match accuracy. Partial payment and mismatch handling verified. Human fallback process documented.",
  },
] as const;

const UPCOMING_AGENTS = [
  {
    id: "A05",
    name: "Staffing Agent",
    function:
      "Workforce management for labour-intensive verticals and shift-heavy teams.",
    capabilities: [
      "Staff rostering and shift scheduling",
      "Leave management and approval",
      "Contractor coordination",
      "Payroll preparation and reporting",
    ],
    integrations: "To be confirmed upon Phase 2 spec delivery",
    acceptance:
      "Successfully executes rostering, leave, and payroll prep workflows during UAT with documented edge case handling.",
  },
  {
    id: "A06",
    name: "Client Communication & Follow-up Agent",
    function: "Relationship and engagement layer that works across all agents.",
    capabilities: [
      "Monitors WhatsApp, email, and Telegram for client communications",
      "Sends automated triggered follow-ups based on events from other agents",
      "Handles basic client queries via RAG knowledge base",
      "Logs all communications for CRM and audit trail",
      "Generates monthly engagement and satisfaction summaries",
    ],
    integrations: "WhatsApp, email, Telegram, CRM platforms",
    acceptance:
      "Successfully triggers, sends, and logs automated follow-ups during UAT. RAG knowledge base query accuracy verified. Full audit trail confirmed.",
  },
] as const;

export default function Home() {
  return (
    <main className="min-h-screen bg-background px-4 py-6 text-text-primary md:px-8 lg:px-12 xl:px-16">
      <div className="mx-auto w-full max-w-full">
        <section className="relative overflow-hidden rounded-xs border border-border-5 bg-surface p-6 md:p-10">
          <div className="pointer-events-none absolute -top-20 -right-16 h-64 w-64 rounded-full bg-background-blue/10 blur-2xl" />
          <div className="pointer-events-none absolute -bottom-24 -left-12 h-64 w-64 rounded-full bg-emerald-500/10 blur-2xl" />

          <div className="relative grid gap-8 lg:grid-cols-12 lg:items-end">
            <div className="space-y-5 lg:col-span-8">
              <p className="inline-flex rounded-xs border border-border-5 bg-background-5 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-text-secondary">
                Tiger Scale Platform
              </p>
              <h1 className="max-w-4xl text-4xl font-semibold leading-tight text-text-primary sm:text-5xl lg:text-6xl">
                Build, Launch, And Monitor AI Agents With Confidence
              </h1>
              <p className="max-w-3xl text-base leading-7 text-text-secondary sm:text-lg">
                Manage onboarding, client operations, and enterprise controls
                from one clean workspace. Explore both client and admin surfaces
                designed for speed, clarity, and operational focus.
              </p>
              <div className="flex flex-wrap gap-3">
                <Link
                  href="/sign-in"
                  className="inline-flex rounded-xs bg-background-blue px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-background-blue/90"
                >
                  Login
                </Link>
                <Link
                  href="/onboarding"
                  className="inline-flex rounded-xs border border-border-5 bg-background-5 px-5 py-2.5 text-sm font-semibold text-text-secondary transition hover:border-border-5"
                >
                  Start Onboarding
                </Link>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:col-span-4 lg:grid-cols-1">
              <div className="rounded-xs border border-border-5 bg-background-5 p-4">
                <p className="text-2xl font-semibold text-text-primary">06</p>
                <p className="mt-1 text-xs uppercase tracking-wider text-text-muted">
                  Onboarding Steps
                </p>
              </div>
              <div className="rounded-xs border border-border-5 bg-background-5 p-4">
                <p className="text-2xl font-semibold text-text-primary">02</p>
                <p className="mt-1 text-xs uppercase tracking-wider text-text-muted">
                  Dedicated Dashboards
                </p>
              </div>
              <div className="rounded-xs border border-border-5 bg-background-5 p-4">
                <p className="text-2xl font-semibold text-text-primary">∞</p>
                <p className="mt-1 text-xs uppercase tracking-wider text-text-muted">
                  API Integration Ready
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="relative mt-5 overflow-hidden rounded-xs border border-border-5 bg-surface p-6 md:p-8">
          <div className="pointer-events-none absolute -top-16 -right-16 h-52 w-52 rounded-full bg-background-blue/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-20 -left-10 h-52 w-52 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-muted">
                Agent Catalogue
              </p>
              <h2 className="mt-1 text-2xl font-semibold text-text-primary">
                Core Agents For Current Rollout
              </h2>
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {CORE_AGENTS.map((agent) => (
              <article
                key={agent.id}
                className="rounded-xs border border-border-5 bg-background-5 p-5 transition hover:bg-background-5"
              >
                <h3 className="mt-2 text-lg font-semibold text-text-primary">
                  {agent.name}
                </h3>
                <p className="mt-1 text-sm text-text-secondary">
                  <span className="font-semibold text-text-primary">
                    Function:
                  </span>{" "}
                  {agent.function}
                </p>
                <ul className="mt-3 space-y-1 text-sm text-text-secondary">
                  {agent.capabilities.map((item) => (
                    <li key={item}>- {item}</li>
                  ))}
                </ul>
                <p className="mt-3 text-sm text-text-secondary">
                  <span className="font-semibold text-text-primary">
                    Integrations:
                  </span>{" "}
                  {agent.integrations}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="relative mt-5 overflow-hidden rounded-xs border border-border-5 bg-surface p-6 md:p-8">
          <div className="pointer-events-none absolute -top-16 -left-14 h-52 w-52 rounded-full bg-background-blue/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-20 -right-10 h-52 w-52 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="rounded-xs bg-background-blue px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white">
                Upcoming
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {UPCOMING_AGENTS.map((agent) => (
              <article
                key={agent.id}
                className="relative rounded-xs border border-dashed border-border-5 bg-background-5 p-5 transition hover:bg-background-5"
              >
                <h3 className="mt-2 text-lg font-semibold text-text-primary">
                  {agent.name}
                </h3>
                <p className="mt-1 text-sm text-text-secondary">
                  <span className="font-semibold text-text-primary">
                    Function:
                  </span>{" "}
                  {agent.function}
                </p>
                <ul className="mt-3 space-y-1 text-sm text-text-secondary">
                  {agent.capabilities.map((item) => (
                    <li key={item}>- {item}</li>
                  ))}
                </ul>
                <div className="pointer-events-none absolute inset-0 mt-20 rounded-xs bg-background/20 backdrop-blur-[1px]" />
              </article>
            ))}
          </div>
        </section>

        <footer className="mt-5 rounded-xs border border-border-5 bg-surface p-6 md:p-8">
          <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="text-lg font-semibold text-text-primary">
                Tiger Scale
              </p>
              <p className="mt-2 text-sm leading-6 text-text-secondary">
                Unified platform surface for onboarding, agent delivery, and
                enterprise operations.
              </p>
            </div>

            <div>
              <p className="text-sm font-semibold text-text-primary">
                Authentication
              </p>
              <div className="mt-3 space-y-2 text-sm text-text-secondary">
                <Link
                  href="/sign-in"
                  className="block hover:text-background-blue"
                >
                  Sign In
                </Link>
                <Link
                  href="/sign-up"
                  className="block hover:text-background-blue"
                >
                  Sign Up
                </Link>
                <Link
                  href="/forgot-password"
                  className="block hover:text-background-blue"
                >
                  Forgot Password
                </Link>
                <Link
                  href="/reset-password"
                  className="block hover:text-background-blue"
                >
                  Reset Password
                </Link>
              </div>
            </div>

            <div>
              <p className="text-sm font-semibold text-text-primary">
                Platform
              </p>
              <div className="mt-3 space-y-2 text-sm text-text-secondary">
                <Link
                  href="/onboarding"
                  className="block hover:text-background-blue"
                >
                  Onboarding
                </Link>
                <Link
                  href="/client-dashboard"
                  className="block hover:text-background-blue"
                >
                  Client Dashboard
                </Link>
                <Link
                  href="/admin-dashboard"
                  className="block hover:text-background-blue"
                >
                  Admin Dashboard
                </Link>
                <Link
                  href="/auth/callback"
                  className="block hover:text-background-blue"
                >
                  Auth Callback
                </Link>
              </div>
            </div>

            <div>
              <p className="text-sm font-semibold text-text-primary">
                Quick Navigation
              </p>
              <div className="mt-3 space-y-2 text-sm text-text-secondary">
                <Link href="/" className="block hover:text-background-blue">
                  Home
                </Link>
                <Link
                  href="/sign-in"
                  className="block hover:text-background-blue"
                >
                  Start Session
                </Link>
                <Link
                  href="/admin-dashboard/requests"
                  className="block hover:text-background-blue"
                >
                  Review Requests
                </Link>
                <Link
                  href="/admin-dashboard/logs"
                  className="block hover:text-background-blue"
                >
                  System Logs
                </Link>
              </div>
            </div>
          </div>

          <div className="mt-8 border-t border-border-5 pt-4 text-xs text-text-muted">
            © 2026 Tiger Scale. All rights reserved.
          </div>
        </footer>
      </div>
    </main>
  );
}
