"use client";

import { FormEvent, Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { resetPassword } from "@/lib/api";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { sanitizeSecretLike } from "@/lib/input-validation";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = useMemo(() => searchParams.get("token") ?? "", [searchParams]);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();

    if (!token) {
      setError("Missing reset token");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    setError(null);
    setMessage(null);

    try {
      const result = await resetPassword(token, newPassword);
      setMessage(result.message ?? "Password updated successfully");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />

      <section className="max-w-full mx-auto flex w-full flex-1 items-center">
        <div className="mx-auto w-full max-w-xl p-6 shadow-sm md:p-16">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary">
            Create new password
          </h1>

          <form onSubmit={onSubmit} className="mt-7 space-y-4">
            <label className="block text-sm font-medium text-text-secondary">
              New password
              <div className="relative mt-2">
                <input
                  type={showNewPassword ? "text" : "password"}
                  required
                  minLength={8}
                  maxLength={128}
                  value={newPassword}
                  onChange={(e) =>
                    setNewPassword(sanitizeSecretLike(e.target.value, 128))
                  }
                  className="w-full rounded-xs border border-border-5 bg-background-5 px-4 py-3 pr-11 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
                />
                <button
                  type="button"
                  onClick={() => setShowNewPassword((prev) => !prev)}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-text-muted"
                  aria-label={
                    showNewPassword ? "Hide password" : "Show password"
                  }
                >
                  {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>

            <label className="block text-sm font-medium text-text-secondary">
              Confirm password
              <div className="relative mt-2">
                <input
                  type={showConfirmPassword ? "text" : "password"}
                  required
                  minLength={8}
                  maxLength={128}
                  value={confirmPassword}
                  onChange={(e) =>
                    setConfirmPassword(sanitizeSecretLike(e.target.value, 128))
                  }
                  className="w-full rounded-xs border border-border-5 bg-background-5 px-4 py-3 pr-11 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword((prev) => !prev)}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-text-muted"
                  aria-label={
                    showConfirmPassword ? "Hide password" : "Show password"
                  }
                >
                  {showConfirmPassword ? (
                    <EyeOff size={18} />
                  ) : (
                    <Eye size={18} />
                  )}
                </button>
              </div>
            </label>

            {message ? (
              <p className="text-sm text-text-success">{message}</p>
            ) : null}
            {error ? <p className="text-sm text-text-danger">{error}</p> : null}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xs bg-background-blue px-4 py-3 text-lg font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Updating..." : "Update password"}
            </button>

            <p className="mt-6 text-center text-sm text-text-muted">
              <Link
                href="/sign-in"
                className="font-semibold text-background-blue hover:underline"
              >
                Back to sign in
              </Link>
            </p>
          </form>
        </div>
      </section>

      <GlobalFooter />
    </main>
  );
}

function ResetPasswordFallback() {
  return (
    <main className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <section className="max-w-full mx-auto flex w-full flex-1 items-center">
        <div className="mx-auto w-full max-w-xl p-6 shadow-sm md:p-16">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary">
            Create new password
          </h1>
          <p className="mt-7 text-sm text-text-secondary">
            Loading reset link...
          </p>
          <p className="mt-6 text-sm text-text-muted">
            <Link
              href="/sign-in"
              className="font-semibold text-background-blue hover:underline"
            >
              Back to sign in
            </Link>
          </p>
        </div>
      </section>
      <GlobalFooter />
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
