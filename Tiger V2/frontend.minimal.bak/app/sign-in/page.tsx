"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { setTenantId } from "@/lib/api";

export default function SignInPage() {
  const router = useRouter();
  const [tenant, setTenant] = useState("tnt_demo");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!tenant.trim()) {
      setError("Tenant id is required");
      return;
    }
    setTenantId(tenant.trim());
    router.push("/activation");
  }

  return (
    <section className="mx-auto max-w-md space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900">Sign in</h1>
        <p className="mt-1 text-sm text-zinc-600">
          Slice 1 stub: provide a tenant id; this is sent as the
          <code className="mx-1 rounded bg-zinc-100 px-1 py-0.5 text-xs">
            X-Tigeri-Tenant-Id
          </code>
          header on every request. JWT auth lands in a later slice.
        </p>
      </div>
      <form onSubmit={onSubmit} className="space-y-3">
        <label className="block text-sm font-medium text-zinc-800">
          Tenant id
          <input
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
            className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm"
            placeholder="tnt_demo"
          />
        </label>
        {error && <div className="text-sm text-red-600">{error}</div>}
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800"
        >
          Continue
        </button>
      </form>
    </section>
  );
}
