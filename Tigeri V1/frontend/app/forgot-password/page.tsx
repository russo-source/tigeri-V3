"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { requestPasswordReset } from "@/lib/api";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { isValidEmailFormat, sanitizeEmailInput } from "@/lib/input-validation";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();

    if (!isValidEmailFormat(email)) {
      window.alert("Please enter a valid email address.");
      setError("Please enter a valid email address.");
      return;
    }

    setLoading(true);
    setError(null);
    setMessage(null);

    try {
      const result = await requestPasswordReset(email);
      setMessage(
        result.message ?? "If account exists, reset instructions were sent.",
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to request password reset",
      );
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
            Reset your password
          </h1>

          <form onSubmit={onSubmit} className="mt-7 space-y-4">
            <label className="block text-sm font-medium text-text-secondary">
              Email
              <input
                type="email"
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(sanitizeEmailInput(e.target.value))}
                onBlur={() => {
                  if (email && !isValidEmailFormat(email)) {
                    window.alert("Please enter a valid email address.");
                  }
                }}
                placeholder="Email"
                className="mt-2 w-full rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
              />
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
              {loading ? "Sending..." : "Send reset link"}
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
