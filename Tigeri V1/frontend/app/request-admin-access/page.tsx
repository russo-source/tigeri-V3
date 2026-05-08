"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { requestAdminAccess } from "@/lib/api";
import {
  isValidEmailFormat,
  sanitizeEmailInput,
  sanitizeSecretLike,
} from "@/lib/input-validation";

export default function RequestAdminAccessPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (!isValidEmailFormat(email)) {
      setError("Please enter a valid email address.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      await requestAdminAccess({ name, email, password });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <main className="flex min-h-screen flex-col bg-background text-text-primary">
        <GlobalHeader />
        <section className="max-w-full mx-auto flex w-full flex-1 items-center">
          <div className="mx-auto w-full max-w-xl p-6 shadow-sm md:p-16">
            <h1 className="text-4xl font-semibold tracking-tight text-text-primary">
              Request submitted
            </h1>
            <p className="mt-2 text-base text-text-secondary">
              Your admin access request has been received.
            </p>

            <div className="mt-7 space-y-5">
              <div className="flex flex-col items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-6 py-8 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-background-5">
                  <ShieldCheck className="h-6 w-6 text-background-blue" />
                </div>
                <p className="text-sm font-medium text-text-primary">
                  We&apos;ve received your request
                </p>
                <p className="text-sm text-text-secondary">
                  An existing admin will review your request. This process
                  typically takes up to 48 hours. You&apos;ll be able to sign in
                  once approved.
                </p>
              </div>

              <Link
                href="/sign-in"
                className="block w-full rounded-xs bg-background-blue px-4 py-3 text-center text-base font-semibold text-white shadow-[0_8px_20px_rgba(53,55,215,0.28)]"
              >
                Back to sign in
              </Link>

              <p className="text-center text-sm text-text-muted">
                Need immediate help?{" "}
                <Link
                  href="/sign-in"
                  className="font-semibold text-background-blue hover:underline"
                >
                  Return to sign in
                </Link>
              </p>
            </div>
          </div>
        </section>
        <GlobalFooter />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <section className="max-w-full mx-auto flex w-full flex-1 items-center">
        <div className="mx-auto w-full max-w-xl p-6 shadow-sm md:p-16">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary">
            Request admin access
          </h1>
          <p className="mt-2 text-base text-text-secondary">
            Submit your details, an existing admin will review your request
          </p>

          <form className="mt-7 space-y-4" onSubmit={onSubmit}>
            <label className="block text-sm font-medium text-text-secondary">
              Full name
              <input
                type="text"
                required
                maxLength={255}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your full name"
                className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
              />
            </label>

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
                    setError("Please enter a valid email address.");
                  } else {
                    setError(null);
                  }
                }}
                placeholder="you@company.com"
                className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
              />
            </label>

            <label className="block text-sm font-medium text-text-secondary">
              Password
              <div className="relative mt-2">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={8}
                  maxLength={128}
                  value={password}
                  onChange={(e) =>
                    setPassword(sanitizeSecretLike(e.target.value, 128))
                  }
                  placeholder="Min. 8 characters"
                  className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 pr-11 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-text-muted"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>

            <div className="rounded-xs border border-border-5 bg-background-5 px-4 py-3">
              <p className="text-xs text-background-blue">
                Admin slots are limited to 2. Your request will be reviewed by
                an existing admin before access is granted.
              </p>
            </div>

            {error && <p className="text-sm text-text-danger">{error}</p>}

            <motion.button
              type="submit"
              disabled={loading}
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.99 }}
              className="w-full rounded-xs bg-background-blue px-4 py-3 text-base font-semibold text-white shadow-[0_8px_20px_rgba(53,55,215,0.28)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Submitting..." : "Request access"}
            </motion.button>

            <p className="mt-6 text-center text-sm text-text-muted">
              Already have an account?{" "}
              <Link
                href="/sign-in"
                className="font-semibold text-background-blue hover:underline"
              >
                Sign in
              </Link>
            </p>
          </form>
        </div>
      </section>
      <GlobalFooter />
    </main>
  );
}
