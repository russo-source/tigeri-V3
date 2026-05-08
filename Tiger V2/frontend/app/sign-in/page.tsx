"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { signIn } from "@/lib/auth";

export default function SignInPage() {
  const router = useRouter();

  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onAuthSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const scope = await signIn({
        tenant_slug: tenantSlug.trim(),
        email: email.trim(),
        password,
      });
      if (scope.must_change_password) {
        router.replace("/change-password");
        return;
      }
      const next = scope.role === "owner" || scope.role === "admin" ? "/admin" : "/client-dashboard/home";
      router.replace(next);
    } catch (e) {
      setError((e as Error).message);
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
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm text-text-secondary">
            Sign in with your workspace account.
          </p>

          <form onSubmit={onAuthSubmit} className="mt-6 space-y-4">
            <label className="block text-sm font-medium">
              Tenant slug
              <input
                value={tenantSlug}
                onChange={(e) => setTenantSlug(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                placeholder="acme-corp"
                autoComplete="organization"
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Email
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                autoComplete="email"
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                autoComplete="current-password"
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
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-6 text-xs text-text-muted">
            Don&apos;t have an account?{" "}
            <Link href="/sign-up" className="text-navy hover:underline">
              Provision a tenant
            </Link>
            .
          </p>
        </motion.section>
      </main>
      <GlobalFooter />
    </div>
  );
}
