import Link from "next/link";

export default function HomePage() {
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-zinc-900">Tigeri.ai</h1>
        <p className="mt-2 max-w-2xl text-zinc-600">
          Business automation platform built around a library of specialised AI
          agents. Each agent automates a specific operational function. Clients
          deploy the agents they need, individually or as a suite.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Link
          href="/sign-in"
          className="rounded-lg border border-zinc-200 bg-white p-5 hover:border-zinc-300"
        >
          <div className="text-sm font-medium text-zinc-900">1. Sign in</div>
          <div className="mt-1 text-sm text-zinc-500">
            Identify your tenant to begin the activation flow.
          </div>
        </Link>
        <Link
          href="/activation"
          className="rounded-lg border border-zinc-200 bg-white p-5 hover:border-zinc-300"
        >
          <div className="text-sm font-medium text-zinc-900">2. Activation</div>
          <div className="mt-1 text-sm text-zinc-500">
            Connect your CRM via MCP or API. Tigeri reasons over your capabilities
            and ranks agents.
          </div>
        </Link>
        <Link
          href="/agents"
          className="rounded-lg border border-zinc-200 bg-white p-5 hover:border-zinc-300"
        >
          <div className="text-sm font-medium text-zinc-900">3. Deploy agents</div>
          <div className="mt-1 text-sm text-zinc-500">
            Browse the agent catalog. Deploy from the recommendations.
          </div>
        </Link>
      </div>
    </section>
  );
}
