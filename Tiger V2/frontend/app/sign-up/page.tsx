"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import { signUp } from "@/lib/auth";

export default function SignUpPage() {
  const router = useRouter();
  const [tenantName, setTenantName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signUp({
        tenant_name: tenantName.trim(),
        email: email.trim(),
        name: name.trim(),
        password,
      });
      router.replace("/activation");
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
          <h1 className="text-2xl font-semibold tracking-tight">
            Provision a tenant
          </h1>
          <p className="mt-2 text-sm text-text-secondary">
            Creates a workspace, an owner user, and signs you in via an
            HTTP-only session cookie. The tenant slug is generated from your
            organisation name.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <label className="block text-sm font-medium">
              Organisation name
              <input
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                placeholder="Acme Pty Ltd"
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Your name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-navy"
                placeholder="Sarah Chen"
                autoComplete="name"
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Work email
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
              {busy ? "Provisioning…" : "Continue to activation"}
            </button>
          </form>

          <p className="mt-6 text-xs text-text-muted">
            Already have a tenant?{" "}
            <Link href="/sign-in" className="text-navy hover:underline">
              Sign in
            </Link>
            .
          </p>
        </motion.section>
      </main>
      <GlobalFooter />
    </div>
  );
}
