"use client";

import { useState } from "react";

import { api, getTenantId } from "@/lib/api";
import type { InvoiceOutput } from "@/lib/types";

const SAMPLE = `vendor: Globex Logistics
currency: AUD
total: 1500.00
tax: 150.00
invoice: INV-7788
due: 2026-06-15`;

export default function InvoiceInboxPage() {
  const [text, setText] = useState(SAMPLE);
  const [result, setResult] = useState<InvoiceOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const tenantId = getTenantId();
      if (!tenantId) {
        setError("No tenant id set. Sign in first.");
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
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold text-zinc-900">Invoice inbox</h1>
      <p className="text-sm text-zinc-600">
        Paste raw invoice text below to run the Invoice Agent end-to-end. The
        slice 1 inbox uses an inline document; in production this would be an S3
        object reference (<code>s3://…</code>).
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        className="w-full rounded-md border border-zinc-300 bg-white p-3 font-mono text-xs"
      />
      <button
        onClick={submit}
        disabled={busy}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:bg-zinc-300"
      >
        {busy ? "Running…" : "Run Invoice Agent"}
      </button>
      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}
      {result && (
        <div className="space-y-2 rounded-md border border-zinc-200 bg-white p-4 text-sm">
          <Row label="Invoice id" value={result.invoice_id} />
          <Row label="Vendor" value={result.vendor_name} />
          <Row label="Amount" value={`${result.amount_total} ${result.currency}`} />
          <Row label="Validation" value={result.validation_status} />
          <Row label="Approval" value={result.approval_status} />
          <Row label="Posting" value={result.posting_status} />
          <Row label="GL ref" value={result.posting_reference || "—"} />
        </div>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-zinc-500">{label}</span>
      <span className="font-medium text-zinc-900">{value}</span>
    </div>
  );
}
