"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff, ShieldCheck, ShieldX, UserCheck } from "lucide-react";
import {
  getPendingAdminRequests,
  approveAdminAccessRequest,
  rejectAdminAccessRequest,
} from "@/lib/api";
import { AdminAccessSkeleton } from "@/components/ui/skeletons";

type PendingAdmin = { email: string; name: string };

export default function AdminAccessPage() {
  const [pending, setPending] = useState<PendingAdmin[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rejectingEmail, setRejectingEmail] = useState<string | null>(null);

  // Secret modal state
  const [approveTarget, setApproveTarget] = useState<PendingAdmin | null>(null);
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [approving, setApproving] = useState(false);
  const [secretError, setSecretError] = useState<string | null>(null);

  async function load() {
    try {
      const res = await getPendingAdminRequests();
      setPending(res.pending);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const openApproveModal = (req: PendingAdmin) => {
    setApproveTarget(req);
    setSecret("");
    setSecretError(null);
    setShowSecret(false);
  };

  const closeModal = () => {
    setApproveTarget(null);
    setSecret("");
    setSecretError(null);
  };

  const onConfirmApprove = async () => {
    if (!approveTarget) return;
    if (!secret.trim()) {
      setSecretError("Please enter the admin secret key.");
      return;
    }
    setApproving(true);
    setSecretError(null);
    try {
      await approveAdminAccessRequest(approveTarget.email, secret);
      setPending((p) => p.filter((x) => x.email !== approveTarget.email));
      closeModal();
    } catch (err) {
      setSecretError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  };

  const onReject = async (email: string) => {
    setRejectingEmail(email);
    try {
      await rejectAdminAccessRequest(email);
      setPending((p) => p.filter((x) => x.email !== email));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setRejectingEmail(null);
    }
  };

  if (isLoading) {
    return <AdminAccessSkeleton />;
  }

  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          Admin Access
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Review and approve admin access requests. Maximum 2 admins allowed.
        </p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <div className="flex items-center gap-2 mb-4">
          <UserCheck className="h-4 w-4 text-background-blue" />
          <p className="text-sm font-medium text-text-primary">
            Pending Requests
          </p>
          {pending.length > 0 && (
            <span className="ml-auto rounded-full bg-background-5 px-2 py-0.5 text-xs text-background-blue">
              {pending.length}
            </span>
          )}
        </div>

        {pending.length === 0 ? (
          <p className="py-6 text-center text-sm text-text-muted">
            No pending admin access requests.
          </p>
        ) : (
          <div className="space-y-2">
            {pending.map((req) => (
              <div
                key={req.email}
                className="flex items-center justify-between rounded-xs border border-border-5 bg-background-5 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-text-primary">
                    {req.name}
                  </p>
                  <p className="text-xs text-text-muted">{req.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openApproveModal(req)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-background-blue px-3 py-1.5 text-xs text-white disabled:opacity-50"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Approve
                  </button>
                  <button
                    onClick={() => void onReject(req.email)}
                    disabled={rejectingEmail === req.email}
                    className="border-ui-danger inline-flex items-center gap-1.5 rounded-xs border px-3 py-1.5 text-xs text-text-danger disabled:opacity-50"
                  >
                    <ShieldX className="h-3.5 w-3.5" />
                    {rejectingEmail === req.email ? "Rejecting..." : "Reject"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Secret confirmation modal */}
      {approveTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={(e) => {
            if (e.target === e.currentTarget) closeModal();
          }}
        >
          <div className="w-full max-w-sm rounded-xs border border-border-5 bg-surface p-6 shadow-xl">
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="h-5 w-5 text-background-blue" />
              <p className="text-base font-semibold text-text-primary">
                Confirm approval
              </p>
            </div>
            <p className="text-sm text-text-secondary mb-4">
              You are granting admin access to{" "}
              <span className="font-medium text-text-primary">
                {approveTarget.name}
              </span>{" "}
              ({approveTarget.email}). Enter the admin secret key to confirm.
            </p>

            <div className="relative">
              <input
                type={showSecret ? "text" : "password"}
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void onConfirmApprove();
                }}
                placeholder="Enter admin secret key"
                className="border-ui-input h-11 w-full rounded-xs border px-4 pr-11 text-sm outline-none placeholder:text-zinc-400 focus:border-background-blue"
              />
              <button
                type="button"
                onClick={() => setShowSecret((p) => !p)}
                className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-zinc-400"
              >
                {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>

            {secretError && (
              <p className="mt-2 text-xs text-red-600">{secretError}</p>
            )}

            <div className="mt-4 flex gap-2">
              <button
                onClick={closeModal}
                className="flex-1 rounded-xs border border-border-5 px-4 py-2.5 text-sm text-text-primary"
              >
                Cancel
              </button>
              <button
                onClick={() => void onConfirmApprove()}
                disabled={approving}
                className="flex-1 rounded-xl bg-background-blue px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              >
                {approving ? "Verifying..." : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
