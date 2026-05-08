"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  CircleAlert,
  CircleCheckBig,
  Clock3,
  Mail,
  RefreshCcw,
  Shield,
  ShieldAlert,
} from "lucide-react";
import { getClientRequests, getCurrentUser } from "@/lib/api";
import type { ClientRequest } from "@/lib/type";
import { formatDate } from "@/lib/helper";
import FullPageLoader from "@/components/ui/full-page-loader";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";

function statusBadge(status: "pending" | "approved" | "rejected") {
  if (status === "approved") {
    return "border border-emerald-400/40 bg-emerald-500/10 text-emerald-300";
  }

  if (status === "rejected") {
    return "border border-red-400/40 bg-red-500/10 text-red-300";
  }

  return "border border-border-10 bg-background-5 text-text-secondary";
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border-5 py-2.5 last:border-b-0">
      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
      </span>
      <span className="text-right text-sm text-text-primary">{value}</span>
    </div>
  );
}

function PendingView({ request }: { request: ClientRequest }) {
  return (
    <>
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-background-5 text-background-blue">
        <Clock3 className="h-7 w-7" />
      </div>

      <h1 className="mt-5 text-center text-4xl font-semibold tracking-tight text-text-primary">
        Waiting for approval
      </h1>
      <p className="mx-auto mt-3 max-w-xl text-center text-base text-text-secondary">
        Your access request has been submitted and is now under review by our
        admin team. You will receive an update once a decision is made.
      </p>

      <div className="mt-6 rounded-xs border border-border-5 bg-background-5 p-4">
        <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-2 text-center text-xs md:text-sm">
          <div>
            <div className="mx-auto mb-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500 text-white">
              <CircleCheckBig className="h-4 w-4" />
            </div>
            <p className="font-medium text-text-primary">Request submitted</p>
          </div>
          <span className="h-0.5 w-full bg-emerald-400/60" />

          <div>
            <div className="mx-auto mb-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-background-blue text-white">
              2
            </div>
            <p className="font-medium text-text-primary">Under review</p>
          </div>
          <span className="h-0.5 w-full bg-border-10" />

          <div>
            <div className="mx-auto mb-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-surface-elevated text-text-muted">
              3
            </div>
            <p className="font-medium text-text-muted">Access granted</p>
          </div>
        </div>
      </div>

      <div className="mt-5 rounded-xs border border-border-5 bg-surface p-4">
        <InfoRow
          label="Request ID"
          value={`REQ-${String(request.id).slice(-4)}`}
        />
        <InfoRow label="Submitted" value={formatDate(request.created_at)} />
        <InfoRow label="Status" value="Under review" />
        <InfoRow label="Estimated review time" value="1-2 business days" />
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex items-center justify-center gap-2 rounded-xs border border-border-5 bg-background-5 px-4 py-2.5 text-sm font-medium text-text-primary hover:bg-background-10"
        >
          <RefreshCcw className="h-4 w-4" />
          Check status
        </button>

        <a
          href="mailto:support@tigeri.ai"
          className="inline-flex items-center justify-center gap-2 rounded-xs border border-border-5 bg-background-5 px-4 py-2.5 text-sm font-medium text-text-primary hover:bg-background-10"
        >
          <Mail className="h-4 w-4" />
          Contact support
        </a>
      </div>
    </>
  );
}

function ApprovedView({ request }: { request: ClientRequest }) {
  return (
    <>
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
        <CheckCircle2 className="h-8 w-8" />
      </div>
      <h1 className="mt-5 text-center text-4xl font-semibold tracking-tight text-text-primary">
        Request approved
      </h1>
      <p className="mx-auto mt-3 max-w-xl text-center text-base text-text-secondary">
        Welcome aboard. Your first access request has been approved and your
        workspace is ready.
      </p>

      <div className="mt-6 rounded-xs border border-emerald-400/40 bg-emerald-500/10 p-4">
        <div className="mb-2 flex items-center gap-2 text-emerald-300">
          <Shield className="h-4 w-4" />
          <p className="text-base font-semibold">Access granted</p>
        </div>
        <InfoRow label="Decision" value="Approved" />
        <InfoRow label="Date" value={formatDate(request.created_at)} />
        <InfoRow
          label="Request"
          value={`REQ-${String(request.id).slice(-4)}`}
        />
        <InfoRow label="Approved by" value="Admin team" />
      </div>

      <div className="mt-5 rounded-xs border border-border-5 bg-background-5 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          What you can do now
        </p>
        <ul className="mt-3 space-y-2 text-sm text-text-secondary">
          <li>Submit new agent requests from client dashboard</li>
          <li>Configure and connect integrations</li>
          <li>Monitor your agent performance and logs</li>
        </ul>
      </div>

      <Link
        href="/client-dashboard/home"
        className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xs bg-background-blue px-4 py-3 text-base font-semibold text-white hover:opacity-90"
      >
        Go to dashboard
      </Link>
    </>
  );
}

function RejectedView({ request }: { request: ClientRequest }) {
  return (
    <>
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-500/15 text-red-300">
        <CircleAlert className="h-8 w-8" />
      </div>
      <h1 className="mt-5 text-center text-4xl font-semibold tracking-tight text-text-primary">
        Request declined
      </h1>
      <p className="mx-auto mt-3 max-w-xl text-center text-base text-text-secondary">
        Your first access request was not approved at this time. Update your
        details and resubmit for review.
      </p>

      <div className="mt-6 rounded-xs border border-red-400/40 bg-red-500/10 p-4">
        <div className="mb-2 flex items-center gap-2 text-red-300">
          <ShieldAlert className="h-4 w-4" />
          <p className="text-base font-semibold">Review details</p>
        </div>
        <InfoRow label="Decision" value="Declined" />
        <InfoRow label="Date" value={formatDate(request.created_at)} />
        <InfoRow
          label="Request"
          value={`REQ-${String(request.id).slice(-4)}`}
        />
        <InfoRow
          label="Reason"
          value={
            request.admin_notes?.trim() ||
            "Please review your onboarding information."
          }
        />
      </div>

      <div className="mt-5 rounded-xs border border-border-5 bg-background-5 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          What you can do
        </p>
        <ul className="mt-3 space-y-2 text-sm text-text-secondary">
          <li>Resubmit with updated organization details</li>
          <li>Contact support for clarification</li>
          <li>Ensure required fields are completed accurately</li>
        </ul>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <Link
          href="/onboarding"
          className="inline-flex items-center justify-center rounded-xs bg-background-blue px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90"
        >
          Resubmit request
        </Link>

        <a
          href="mailto:support@tigeri.ai"
          className="inline-flex items-center justify-center rounded-xs border border-border-5 bg-background-5 px-4 py-2.5 text-sm font-semibold text-text-primary hover:bg-background-10"
        >
          Contact support
        </a>
      </div>
    </>
  );
}

function FirstRequestStatusPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestIdFromQuery = searchParams.get("requestId");

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requests, setRequests] = useState<ClientRequest[]>([]);

  useEffect(() => {
    async function loadFirstRequestStatus() {
      try {
        const user = await getCurrentUser();
        if (user.is_admin) {
          router.replace("/admin-dashboard/dashboard");
          return;
        }
        const response = await getClientRequests();
        const reqs = response.requests || [];
        setRequests(reqs);

        const latest = [...reqs].sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )[0];

        if (!latest) {
          router.replace("/onboarding");
          return;
        }

        if (latest?.status === "approved") {
          router.replace("/client-dashboard/home");
          return;
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Unable to load request status.",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadFirstRequestStatus();
    const interval = setInterval(() => void loadFirstRequestStatus(), 10000);
    return () => clearInterval(interval);
  }, [router]);
  const selectedRequest = useMemo(() => {
    if (!requests.length) return null;

    if (requestIdFromQuery) {
      const exact = requests.find((r) => r.id === requestIdFromQuery);
      if (exact) return exact;
    }

    return [...requests].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];
  }, [requestIdFromQuery, requests]);

  if (isLoading) {
    return <FullPageLoader />;
  }

  if (error) {
    return (
      <main className="flex min-h-screen flex-col bg-background text-text-primary">
        <GlobalHeader />
        <section className="flex flex-1 items-center justify-center p-4">
          <div className="rounded-xs border border-red-400/40 bg-red-500/10 p-5 text-sm text-red-300">
            {error}
          </div>
        </section>
        <GlobalFooter />
      </main>
    );
  }

  if (!selectedRequest) {
    return <FullPageLoader />;
  }

  return (
    <main className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <section className="px-4 py-8 md:px-6 md:py-10">
        <div className="mx-auto w-full max-w-full">
          <div className="mx-auto w-full max-w-2xl rounded-xs border border-border-10 bg-surface p-6 shadow-[0_10px_40px_rgba(18,31,78,0.12)] md:p-8">
            <div className="mb-5 flex justify-end">
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${statusBadge(selectedRequest.status)}`}
              >
                {selectedRequest.status.toUpperCase()}
              </span>
            </div>

            {selectedRequest.status === "pending" && (
              <PendingView request={selectedRequest} />
            )}
            {selectedRequest.status === "approved" && (
              <ApprovedView request={selectedRequest} />
            )}
            {selectedRequest.status === "rejected" && (
              <RejectedView request={selectedRequest} />
            )}
          </div>
        </div>
      </section>
      <GlobalFooter />
    </main>
  );
}

export default function FirstRequestStatusPage() {
  return (
    <Suspense fallback={<FullPageLoader />}>
      <FirstRequestStatusPageContent />
    </Suspense>
  );
}
