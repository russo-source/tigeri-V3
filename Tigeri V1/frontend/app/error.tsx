"use client";

import { useEffect } from "react";

import { reportError } from "@/lib/observability";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportError(error, { digest: error.digest });
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md rounded-xs border border-border-5 bg-surface p-6 text-center">
        <h2 className="text-xl font-semibold text-text-primary">
          Something went wrong
        </h2>
        <p className="mt-2 text-sm text-text-secondary">
          We could not load this page. Please try again.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-5 rounded-xs bg-background-blue px-4 py-2 text-sm font-semibold text-white"
        >
          Retry
        </button>
      </div>
    </main>
  );
}
