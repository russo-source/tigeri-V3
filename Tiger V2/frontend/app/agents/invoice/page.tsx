"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { api, getTenantId } from "@/lib/api";
import type { InvoiceOutput } from "@/lib/type";

const SAMPLE = `vendor: Globex Logistics
currency: AUD
total: 1500.00
tax: 150.00
invoice: INV-7788
due: 2026-06-15`;

const STATUS_TAG: Record<string, string> = {
  VALID: "tag-success",
  NEEDS_REVIEW: "tag-warning",
  REJECTED: "tag-error",
  APPROVED: "tag-success",
  PENDING: "tag-warning",
  DENIED: "tag-error",
  POSTED: "tag-success",
  NOT_POSTED: "tag-warning",
};

export default function InvoiceInboxPage() {
  const [text, setText] = useState(SAMPLE);
  const [result, setResult] = useState<InvoiceOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const tenantId = getTenantId();
      if (!tenantId) {
        setError("No tenant id; sign in first.");
        return;
      }
      const out = await api.invokeInvoice({
        tenant_id: tenantId,
        source: "UPLOAD",
        document: { media_type: "text/plain", content_ref: `inline:${text}` },
        received_at: new Date().toISOString(),
      });
      setResult(out);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Invoice inbox</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Paste raw invoice text below to run the LangGraph Invoice Agent
          end-to-end. Slice 1 uses an inline document; production uses
          <code className="mx-1 rounded bg-surface px-1.5 py-0.5 text-xs">
            s3://bucket/key
          </code>
          references.
        </p>
      </header>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        className="w-full rounded-md border border-border bg-surface p-3 font-mono text-xs text-text-primary outline-none transition-colors focus:border-navy"
      />

      <button
        onClick={submit}
        disabled={busy}
        className="rounded-md bg-navy px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-dark disabled:opacity-50"
      >
        {busy ? "Running…" : "Run Invoice Agent"}
      </button>

      {error ? (
        <div className="rounded-md border border-danger bg-background p-3 text-sm text-text-danger">
          {error}
        </div>
      ) : null}

      {result && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-md border border-border bg-surface p-5 text-sm"
        >
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
            Result
          </h2>
          <dl className="mt-3 space-y-2">
            <Row label="Invoice id" value={result.invoice_id} />
            <Row label="Vendor" value={result.vendor_name} />
            <Row
              label="Amount"
              value={`${result.amount_total} ${result.currency} (tax ${result.tax_total})`}
            />
            <Row label="Validation" value={<Tag value={result.validation_status} />} />
            <Row label="Approval" value={<Tag value={result.approval_status} />} />
            <Row label="Posting" value={<Tag value={result.posting_status} />} />
            <Row label="GL ref" value={result.posting_reference || "—"} />
          </dl>
        </motion.div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border-5 pb-2 last:border-b-0">
      <dt className="text-text-muted">{label}</dt>
      <dd className="font-medium text-text-primary">{value}</dd>
    </div>
  );
}

function Tag({ value }: { value: string }) {
  return <span className={STATUS_TAG[value] ?? "tag-info"}>{value}</span>;
}
