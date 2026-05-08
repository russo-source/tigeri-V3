"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { api, ApiError } from "@/lib/api";
import { fetchMe } from "@/lib/auth";

export default function ChangePasswordPage() {
  // Next 15 static-export wraps useSearchParams in a Suspense boundary or
  // the prerender bails. Splitting the form into an inner component keeps
  // the export pipeline happy.
  return (
    <Suspense fallback={null}>
      <ChangePasswordInner />
    </Suspense>
  );
}

function ChangePasswordInner() {
  const router = useRouter();
  const search = useSearchParams();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (next.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (next === current) {
      setError("New password must differ from current password.");
      return;
    }
    if (next !== confirm) {
      setError("Confirmation does not match.");
      return;
    }

    setBusy(true);
    try {
      await api.changePassword(current, next);
      // Re-fetch /auth/me so the local mirror picks up the new flag state,
      // then route to wherever the user came from (or admin/dashboard by role).
      const scope = await fetchMe();
      const target =
        search.get("next") ??
        (scope?.role === "owner" || scope?.role === "admin"
          ? "/admin"
          : "/client-dashboard/home");
      router.replace(target);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `${e.message}`
          : e instanceof Error
            ? e.message
            : "Failed to change password";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="w-full max-w-md rounded-md border border-border bg-surface p-8"
        >
          <h1 className="text-2xl font-semibold tracking-tight">
            Set a new password
          </h1>
          <p className="mt-2 text-sm text-text-secondary">
            Your account requires a password change before you can continue.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <label className="block text-sm font-medium">
              Current password
              <input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                autoComplete="current-password"
                required
              />
            </label>
            <label className="block text-sm font-medium">
              New password
              <input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Confirm new password
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>

            {error ? (
              <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-md bg-navy px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
            >
              {busy ? "Updating…" : "Update password"}
            </button>
          </form>

          <p className="mt-6 text-xs text-text-muted">
            Pick something you don&apos;t use anywhere else. Your operator
            cannot retrieve it; the next reset goes through the same flow.
          </p>
        </motion.section>
      </main>
      <GlobalFooter />
    </div>
  );
}
