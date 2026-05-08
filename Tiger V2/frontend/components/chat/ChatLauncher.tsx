"use client";

import {
  ChangeEvent,
  Fragment,
  KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  Copy,
  Download,
  FileText,
  MessageSquare,
  MoreVertical,
  Paperclip,
  Send,
  ShieldCheck,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
} from "lucide-react";
import { getTenantId } from "@/lib/api";
import {
  ActionResponse,
  ChatEvent,
  ChatTurn,
  HistoryAction,
  UploadedFile,
  cancelAction,
  clearHistory,
  confirmAction,
  loadHistory,
  sendFeedback,
  streamChat,
  uploadFile,
} from "@/lib/chat";
import { ActionState, AgentActionCard } from "./AgentActionCard";
import { Markdown } from "./Markdown";

const HIDE_ON = ["/sign-in", "/sign-up"];

const INVOICE_TEMPLATE = `Raise this invoice:

Vendor: <name>
Total: <amount>
Tax: <amount or %>           (optional)
Tax rate label: <e.g. GST 18%>  (optional)
Currency: INR                (optional, defaults to org's base currency)
Invoice number: <ref>        (optional)
Due date: <YYYY-MM-DD>       (optional, default +30 days)
PO reference: <ref>          (optional)
`;

const QUICK_PROMPTS: { label: string; prompt: string }[] = [
  { label: "Raise an invoice (template)", prompt: INVOICE_TEMPLATE },
  { label: "What can you do?", prompt: "What can you do?" },
  { label: "Show recent audit records", prompt: "Show recent audit records" },
  { label: "Run a P&L for the last 30 days", prompt: "Run a P&L for the last 30 days" },
  { label: "What's my integration health?", prompt: "What's my integration health?" },
  { label: "Onboard a new client", prompt: "Onboard a new client" },
];

const ACCEPTED_FILE_TYPES = ".pdf,.docx,.doc,.txt,.md";

type ProposalState =
  | "pending"
  | "confirming"
  | "executed"
  | "cancelled"
  | "expired"
  | "failed";

type Bubble =
  | { id: string; kind: "user"; text: string; attachment?: { name: string } }
  | {
      id: string;
      kind: "assistant";
      messageId?: string;
      text: string;
      streaming?: boolean;
      rating?: 1 | -1;
    }
  | { id: string; kind: "action"; action: ActionState }
  | {
      id: string;
      kind: "proposal";
      capability: string;
      args: Record<string, unknown>;
      confirmation_token: string;
      expires_at: string;
      state: ProposalState;
      result?: Record<string, unknown> | null;
      error?: string;
    }
  | { id: string; kind: "error"; text: string };

let _bubbleSeq = 0;
const newBubbleId = () => `b_${++_bubbleSeq}`;

function actionFromHistory(a: HistoryAction): ActionState {
  if (a.kind === "agent_run") {
    return {
      kind: "agent_run",
      agent_id: a.agent_id ?? "",
      capabilities: a.capabilities ?? [],
      trace_id: a.trace_id ?? "",
      summary: a.summary ?? "",
    };
  }
  if (a.kind === "tool_done") {
    return {
      kind: "tool_done",
      tool: a.tool ?? "",
      args: a.args ?? {},
      ok: a.ok ?? true,
      summary: a.summary ?? "",
    };
  }
  return { kind: "tool_running", tool: a.tool ?? "", args: a.args ?? {} };
}

function summariseResult(
  result: Record<string, unknown> | unknown[] | undefined,
  ok: boolean,
  tool?: string,
): string {
  if (!ok) {
    // Tool wrappers return {error: "..."} on graceful failures (not connected,
    // bad input, provider rejection). Surface that string instead of "Failed."
    if (result && typeof result === "object" && !Array.isArray(result)) {
      const err = (result as Record<string, unknown>).error;
      if (typeof err === "string" && err) return err.slice(0, 200);
    }
    return "Failed.";
  }
  if (!result) return "Done.";
  if (Array.isArray(result)) return `${result.length} item(s).`;
  if (typeof result === "object" && result) {
    const r = result as Record<string, unknown>;

    // Tool-specific summaries for the read-only Maps / Workspace tools.
    // Without these, every successful call collapsed to "Done." and the
    // user couldn't tell if find_place actually found anything.
    if (tool === "find_place" && typeof r.name === "string") {
      const rating =
        typeof r.rating === "number" ? ` ★${r.rating}` : "";
      const open =
        r.open_now === true ? " · open" : r.open_now === false ? " · closed" : "";
      return `${r.name}${rating}${open}`;
    }
    if (tool === "geocode_address" && typeof r.formatted_address === "string") {
      return r.formatted_address;
    }
    if (tool === "compute_travel_time" && Array.isArray(r.results)) {
      const first = (r.results as Record<string, unknown>[])[0];
      if (first && typeof first.duration_text === "string") {
        return `${first.duration_text} (${first.distance_text ?? ""})`;
      }
    }
    if (tool === "get_weather" && r.current && typeof r.current === "object") {
      const cur = r.current as Record<string, unknown>;
      const cond = typeof cur.condition === "string" ? cur.condition : "";
      const temp = typeof cur.temperature_c === "number" ? `${cur.temperature_c}°C` : "";
      return `${cond}${cond && temp ? " · " : ""}${temp}` || "Done.";
    }
    if (tool === "send_gmail" && typeof r.message_id === "string") {
      return `Email sent (id ${String(r.message_id).slice(0, 16)})`;
    }
    if (tool === "create_calendar_event_with_meet" && typeof r.html_link === "string") {
      const meet =
        typeof r.meet_link === "string" && r.meet_link ? ` · ${r.meet_link}` : "";
      return `Event created${meet}`;
    }
    if (tool === "list_calendar_events" && typeof r.count === "number") {
      return `${r.count} event(s) in window`;
    }
    if (tool === "read_sheet" && typeof r.row_count === "number") {
      return `${r.row_count} row(s) read`;
    }
    if (tool === "create_drive_doc" && typeof r.web_view_link === "string") {
      return `Doc created — ${r.web_view_link}`;
    }
    if (tool === "append_sheet_row" && typeof r.updated_rows === "number") {
      return `${r.updated_rows} row(s) appended`;
    }

    // Generic fallbacks
    if (typeof r.count === "number") return `${r.count} item(s).`;
    if (typeof r.url === "string") return r.url;
    if (typeof r.trace_id === "string") return `trace ${String(r.trace_id).slice(0, 18)}`;
  }
  return "Done.";
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function bubbleToHtml(b: Bubble): string {
  if (b.kind === "user") {
    const att = b.attachment
      ? `<br><em>Attachment: ${escapeHtml(b.attachment.name)}</em>`
      : "";
    return `<div class="msg user"><strong>You</strong>: ${escapeHtml(b.text)}${att}</div>`;
  }
  if (b.kind === "assistant") {
    return `<div class="msg assistant"><strong>Tigeri</strong>: ${escapeHtml(b.text)}</div>`;
  }
  if (b.kind === "error") {
    return `<div class="msg error"><strong>Error</strong>: ${escapeHtml(b.text)}</div>`;
  }
  if (b.kind === "proposal") {
    return `<div class="msg action"><strong>Proposed</strong>: ${escapeHtml(b.capability)} (${b.state})</div>`;
  }
  const a = b.action;
  if (a.kind === "agent_run") {
    return `<div class="msg action"><strong>Agent</strong>: ${escapeHtml(a.agent_id)} — ${escapeHtml(a.summary)}</div>`;
  }
  return `<div class="msg action"><strong>Tool</strong>: ${escapeHtml(a.tool)} — ${escapeHtml((a as { summary?: string }).summary ?? "")}</div>`;
}

function exportToPdf(bubbles: Bubble[]) {
  const html = `<!DOCTYPE html><html><head><title>Tigeri chat export</title>
<meta charset="utf-8"/>
<style>
  body { font-family: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 32px; color: #111827; max-width: 720px; margin: 0 auto; }
  h1 { font-size: 18px; margin-bottom: 4px; color: #040273; }
  .meta { color: #6b7280; font-size: 12px; margin-bottom: 24px; font-family: "IBM Plex Mono", monospace; }
  .msg { margin: 8px 0; padding: 10px 12px; border-radius: 4px; line-height: 1.5; font-size: 13px; border: 1px solid #e5e7eb; }
  .user { background: #040273; color: #ffffff; border-color: #030252; }
  .assistant { background: #f8f9fa; }
  .action { background: #f0f4f8; border-left: 3px solid #040273; font-size: 12px; }
  .error { background: #ffffff; color: #dc2626; border-color: #dc2626; }
  @media print { body { padding: 16px; } }
</style></head><body>
<h1>Tigeri chat export</h1>
<div class="meta">Exported ${new Date().toLocaleString()}</div>
${bubbles.map(bubbleToHtml).join("\n")}
<script>setTimeout(() => window.print(), 200);</script>
</body></html>`;
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(html);
  w.document.close();
}

export default function ChatLauncher() {
  const pathname = usePathname() ?? "/";
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pendingFile, setPendingFile] = useState<UploadedFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setTenantId(getTenantId());
    const onStorage = () => setTenantId(getTenantId());
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [pathname]);

  useEffect(() => {
    if (!open || historyLoaded || !tenantId) return;
    let cancelled = false;
    void (async () => {
      const h = await loadHistory();
      if (cancelled) return;
      const restored: Bubble[] = [];
      for (const m of h.messages) {
        if (m.role === "user") {
          restored.push({ id: newBubbleId(), kind: "user", text: m.content });
        } else {
          for (const a of m.actions) {
            restored.push({
              id: newBubbleId(),
              kind: "action",
              action: actionFromHistory(a),
            });
          }
          if (m.content) {
            restored.push({
              id: newBubbleId(),
              kind: "assistant",
              messageId: m.id,
              text: m.content,
            });
          }
        }
      }
      setBubbles(restored);
      setHistoryLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, historyLoaded, tenantId]);

  useEffect(() => {
    if (open && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [bubbles, open]);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const updateProposal = useCallback(
    (
      bubbleId: string,
      patch: Partial<Extract<Bubble, { kind: "proposal" }>>,
    ) => {
      setBubbles((bs) =>
        bs.map((b) => (b.id === bubbleId && b.kind === "proposal" ? { ...b, ...patch } : b)),
      );
    },
    [],
  );

  const onConfirmProposal = useCallback(
    async (bubble: Extract<Bubble, { kind: "proposal" }>) => {
      if (bubble.state !== "pending") return;
      updateProposal(bubble.id, { state: "confirming" });
      try {
        const res: ActionResponse = await confirmAction(bubble.confirmation_token);
        if (res.status === "executed") {
          updateProposal(bubble.id, { state: "executed", result: res.result });
        } else if (res.status === "failed") {
          updateProposal(bubble.id, {
            state: "failed",
            error: res.error_detail ?? "execution failed",
          });
        } else {
          updateProposal(bubble.id, {
            state: "failed",
            error: `unexpected status ${res.status}`,
          });
        }
      } catch (err) {
        updateProposal(bubble.id, {
          state: "failed",
          error: (err as Error).message,
        });
      }
    },
    [updateProposal],
  );

  const onCancelProposal = useCallback(
    async (bubble: Extract<Bubble, { kind: "proposal" }>) => {
      if (bubble.state !== "pending") return;
      try {
        await cancelAction(bubble.confirmation_token);
      } catch {
        /* swallow — UX still flips to cancelled */
      }
      updateProposal(bubble.id, { state: "cancelled" });
    },
    [updateProposal],
  );

  const onRate = useCallback(
    async (bubble: Bubble, rating: 1 | -1) => {
      if (bubble.kind !== "assistant" || !bubble.messageId) return;
      setBubbles((bs) =>
        bs.map((b) => (b.id === bubble.id && b.kind === "assistant" ? { ...b, rating } : b)),
      );
      try {
        await sendFeedback(bubble.messageId, rating);
      } catch {
        /* swallow */
      }
    },
    [],
  );

  if (HIDE_ON.some((p) => pathname.startsWith(p))) return null;
  if (!tenantId) return null;

  const handleFile = async (f: File) => {
    if (uploading) return;
    setUploading(true);
    try {
      const result = await uploadFile(f);
      setPendingFile(result);
    } catch (err) {
      setBubbles((bs) => [
        ...bs,
        { id: newBubbleId(), kind: "error", text: (err as Error).message },
      ]);
    } finally {
      setUploading(false);
    }
  };

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) void handleFile(f);
    if (e.target) e.target.value = "";
  };

  const onClearHistory = async () => {
    setMenuOpen(false);
    if (!confirm("Clear this entire chat history? This cannot be undone.")) return;
    try {
      await clearHistory();
    } catch {
      /* best-effort */
    }
    setBubbles([]);
    setHistoryLoaded(true);
  };

  const onExportPdf = () => {
    setMenuOpen(false);
    exportToPdf(bubbles);
  };

  const send = async (textOverride?: string) => {
    const baseText = (textOverride ?? input).trim();
    if ((!baseText && !pendingFile) || busy) return;
    if (textOverride === undefined) setInput("");
    setBusy(true);

    const finalText = pendingFile
      ? `${baseText || "Please review this attachment."}\n\n--- Attached: ${pendingFile.filename} (${pendingFile.char_count} chars${pendingFile.truncated ? ", truncated" : ""}) ---\n${pendingFile.text}`
      : baseText;

    const userBubble: Bubble = {
      id: newBubbleId(),
      kind: "user",
      text: baseText || pendingFile?.filename || "Attachment",
      attachment: pendingFile ? { name: pendingFile.filename } : undefined,
    };
    const assistantBubble: Bubble = {
      id: newBubbleId(),
      kind: "assistant",
      text: "",
      streaming: true,
    };
    setBubbles((b) => [...b, userBubble, assistantBubble]);
    setPendingFile(null);

    const history: ChatTurn[] = bubbles
      .filter((b): b is Extract<Bubble, { kind: "user" | "assistant" }> =>
        b.kind === "user" || b.kind === "assistant",
      )
      .map((b) => ({ role: b.kind, content: b.kind === "assistant" ? b.text : b.text }));

    const toolBubbles: Record<string, string> = {};
    abortRef.current = new AbortController();

    const onEvent = (ev: ChatEvent) => {
      if (ev.type === "assistant_message_id") {
        setBubbles((bs) =>
          bs.map((b) =>
            b.id === assistantBubble.id && b.kind === "assistant"
              ? { ...b, messageId: ev.id }
              : b,
          ),
        );
      } else if (ev.type === "agent_text") {
        setBubbles((bs) =>
          bs.map((b) =>
            b.id === assistantBubble.id && b.kind === "assistant"
              ? { ...b, text: b.text + ev.content }
              : b,
          ),
        );
      } else if (ev.type === "tool_call") {
        const id = newBubbleId();
        toolBubbles[ev.id] = id;
        setBubbles((bs) => [
          ...bs,
          { id, kind: "action", action: { kind: "tool_running", tool: ev.tool, args: ev.args } },
        ]);
      } else if (ev.type === "tool_result") {
        const targetId = toolBubbles[ev.id];
        setBubbles((bs) =>
          bs.map((b) => {
            if (b.id !== targetId || b.kind !== "action") return b;
            const prev = b.action;
            const tool =
              prev.kind === "tool_running" || prev.kind === "tool_done" ? prev.tool : "(tool)";
            const args =
              prev.kind === "tool_running" || prev.kind === "tool_done" ? prev.args : {};
            const summary = summariseResult(ev.result, ev.ok, tool);
            return {
              ...b,
              action: {
                kind: "tool_done",
                tool,
                args,
                ok: ev.ok,
                summary,
                result: ev.result,
              },
            };
          }),
        );
      } else if (ev.type === "agent_run") {
        setBubbles((bs) => [
          ...bs,
          {
            id: newBubbleId(),
            kind: "action",
            action: {
              kind: "agent_run",
              agent_id: ev.agent_id,
              capabilities: ev.capabilities,
              trace_id: ev.trace_id,
              summary: ev.summary,
            },
          },
        ]);
      } else if (ev.type === "tool_proposed") {
        setBubbles((bs) => [
          ...bs,
          {
            id: newBubbleId(),
            kind: "proposal",
            capability: ev.capability,
            args: ev.args,
            confirmation_token: ev.confirmation_token,
            expires_at: ev.expires_at,
            state: "pending",
          },
        ]);
      } else if (ev.type === "error") {
        setBubbles((bs) => [
          ...bs,
          { id: newBubbleId(), kind: "error", text: ev.message },
        ]);
      }
    };

    try {
      await streamChat(finalText, history, onEvent, abortRef.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onEvent({ type: "error", message: (err as Error).message });
      }
    } finally {
      setBubbles((bs) =>
        bs.map((b) =>
          b.id === assistantBubble.id && b.kind === "assistant"
            ? { ...b, streaming: false }
            : b,
        ),
      );
      setBusy(false);
      abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void handleFile(f);
  };

  return (
    <>
      {!open ? (
        <button
          aria-label="Open Tigeri chat"
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-50 inline-flex h-12 w-12 items-center justify-center rounded-md border border-navy-darker bg-navy text-white transition-colors hover:bg-navy-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy focus-visible:ring-offset-2"
        >
          <MessageSquare className="h-5 w-5" />
          <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full border border-background bg-success" />
        </button>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className="tigeri-glass fixed bottom-5 right-5 z-50 flex h-[680px] w-[440px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)] flex-col overflow-hidden rounded-md"
        >
          {/* Header */}
          <header className="flex items-center justify-between border-b border-border bg-surface-elevated/60 px-4 py-3">
            <div className="flex items-center gap-2.5">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-navy-darker bg-navy text-white">
                <Bot className="h-4 w-4" />
              </span>
              <div className="flex flex-col leading-tight">
                <span className="text-sm font-semibold text-text-primary tracking-tight">
                  Tigeri
                </span>
                <span className="font-mono text-[10px] text-text-secondary">
                  ONLINE · 8 AGENTS
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <div ref={menuRef} className="relative">
                <button
                  aria-label="Settings"
                  onClick={() => setMenuOpen((v) => !v)}
                  className="rounded-sm p-1.5 text-text-secondary transition-colors hover:bg-background-5 hover:text-text-primary"
                >
                  <MoreVertical className="h-4 w-4" />
                </button>
                {menuOpen ? (
                  <div className="tigeri-glass-card absolute right-0 top-10 z-20 w-56 overflow-hidden rounded-md">
                    <button
                      onClick={onExportPdf}
                      className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-text-primary hover:bg-background-5"
                    >
                      <Download className="h-4 w-4 text-text-secondary" />
                      Export as PDF
                    </button>
                    <button
                      onClick={onClearHistory}
                      className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left text-sm text-text-danger hover:bg-background-5"
                    >
                      <Trash2 className="h-4 w-4" />
                      Clear chat history
                    </button>
                  </div>
                ) : null}
              </div>
              <button
                aria-label="Close chat"
                onClick={() => setOpen(false)}
                className="rounded-sm p-1.5 text-text-secondary transition-colors hover:bg-background-5 hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </header>

          {/* Messages area */}
          <div className="relative flex-1 space-y-3 overflow-y-auto p-4 text-sm">
            {dragOver ? (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface-blue/60 backdrop-blur-sm">
                <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-navy bg-surface-elevated px-7 py-6 text-navy">
                  <Paperclip className="h-6 w-6" />
                  <p className="font-mono text-xs uppercase tracking-wide">Drop PDF or Word file</p>
                </div>
              </div>
            ) : null}
            {bubbles.length === 0 ? (
              <div className="flex flex-col items-center gap-5 py-6 text-center">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-md border border-navy-darker bg-navy text-white">
                  <Bot className="h-5 w-5" />
                </span>
                <div className="space-y-1">
                  <p className="text-base font-semibold tracking-tight text-text-primary">
                    Hi, I&apos;m Tigeri.
                  </p>
                  <p className="text-xs text-text-secondary">
                    I orchestrate your agents. Pick a starter or just ask anything.
                  </p>
                </div>
                <div className="grid w-full grid-cols-1 gap-1.5">
                  {QUICK_PROMPTS.map((p) => {
                    const isTemplate = p.prompt.includes("\n");
                    return (
                      <button
                        key={p.label}
                        onClick={() => {
                          if (isTemplate) {
                            setInput(p.prompt);
                          } else {
                            void send(p.prompt);
                          }
                        }}
                        className="group flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2 text-left text-xs text-text-primary transition-colors hover:bg-surface-blue"
                      >
                        <span className="flex-1">{p.label}</span>
                        <Send className="h-3 w-3 opacity-0 text-text-secondary transition-opacity group-hover:opacity-100" />
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
            {bubbles.map((b) => (
              <BubbleView
                key={b.id}
                b={b}
                onRate={onRate}
                onConfirm={onConfirmProposal}
                onCancel={onCancelProposal}
              />
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Pending attachment chip */}
          {pendingFile ? (
            <div className="border-t border-border bg-surface/60 px-3 py-2">
              <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2">
                <FileText className="h-4 w-4 text-navy" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-text-primary">
                    {pendingFile.filename}
                  </p>
                  <p className="font-mono text-[10px] text-text-secondary">
                    {pendingFile.char_count.toLocaleString()} CHARS
                    {pendingFile.truncated ? " · TRUNCATED" : ""} · READY
                  </p>
                </div>
                <button
                  onClick={() => setPendingFile(null)}
                  className="rounded-sm p-1 text-text-secondary hover:bg-background-5 hover:text-text-primary"
                  aria-label="Remove attachment"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : null}

          {/* Footer / composer */}
          <footer className="border-t border-border bg-surface/60 p-3">
            <div className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_FILE_TYPES}
                onChange={onFileChange}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={busy || uploading}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-surface-elevated text-text-secondary transition-colors hover:border-navy hover:text-navy disabled:opacity-40"
                aria-label="Attach PDF or Word"
                title="Attach PDF or Word file"
              >
                {uploading ? (
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-navy border-t-transparent" />
                ) : (
                  <Paperclip className="h-4 w-4" />
                )}
              </button>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={2}
                placeholder={pendingFile ? "Add a question for the attachment…" : "Ask Tigeri…"}
                disabled={busy}
                className="min-h-[40px] flex-1 resize-none rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-navy disabled:opacity-60"
              />
              {busy ? (
                <button
                  onClick={stop}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-danger bg-danger text-white transition-colors hover:opacity-90"
                  aria-label="Stop generating"
                  title="Stop"
                >
                  <Square className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button
                  onClick={() => void send()}
                  disabled={!input.trim() && !pendingFile}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-navy-darker bg-navy text-white transition-colors hover:bg-navy-dark disabled:opacity-40"
                  aria-label="Send"
                >
                  <Send className="h-4 w-4" />
                </button>
              )}
            </div>
            <p className="mt-2 text-center font-mono text-[10px] uppercase tracking-wide text-text-muted">
              Tigeri can make mistakes. Verify critical actions.
            </p>
          </footer>
        </div>
      )}
    </>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted" />
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* noop */
    }
  };
  return (
    <button
      aria-label="Copy"
      onClick={onClick}
      className="transition-colors hover:text-text-primary"
      title={copied ? "Copied" : "Copy"}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-success" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Executed-state receipt rendering
//
// Backend returns a generic envelope:
//   { trace_id, agent_id, capabilities[], output: <agent-specific dict> }
// The pre-existing UI dumped the whole thing as JSON. We replace that with
// per-capability summary cards so the user sees a clean confirmation
// (vendor, amount, status, link) instead of nested keys. Falls back to a
// compact key-value list for unknown capabilities so we degrade gracefully
// rather than silently hiding new agents' results.
// ────────────────────────────────────────────────────────────────────────

type Json = Record<string, unknown>;

function _str(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "string") return v.trim() || null;
  return String(v);
}

function _money(amount: unknown, currency: unknown): string | null {
  const a = Number(amount);
  if (!Number.isFinite(a)) return null;
  const c = (typeof currency === "string" && currency) || "USD";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: c }).format(a);
  } catch {
    return `${c} ${a.toFixed(2)}`;
  }
}

function _statusTone(value: string | null): "success" | "warning" | "danger" | "muted" {
  if (!value) return "muted";
  const v = value.toUpperCase();
  if (["VALID", "APPROVED", "POSTED", "OK", "CONFIRMED", "MATCHED", "DONE"].includes(v))
    return "success";
  if (["NEEDS_REVIEW", "PENDING", "WAITLISTED", "REVIEW", "UNMATCHED"].includes(v))
    return "warning";
  if (["REJECTED", "DENIED", "FAILED", "DECLINED", "ERROR"].includes(v))
    return "danger";
  return "muted";
}

function StatusPill({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  const tone = _statusTone(value);
  const cls =
    tone === "success"
      ? "border-success/40 text-success"
      : tone === "warning"
        ? "border-warning/40 text-text-warning"
        : tone === "danger"
          ? "border-danger text-text-danger"
          : "border-border text-text-secondary";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm border ${cls} px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide`}
    >
      <span className="text-text-muted">{label}</span>
      <span>{value}</span>
    </span>
  );
}

/** Pull a Xero invoice UUID out of posting_reference if the routing GL
 * adapter hit real Xero. ``posting_reference`` shapes:
 *   "xero:<uuid>"           — real Xero post (we want the PDF here)
 *   "xero_sandbox:inv_..."  — demo/sandbox stub
 *   "qb_sandbox:inv_..."    — QuickBooks sandbox stub
 *   "gl_<ulid>"             — plain stub (no integration connected)
 * Returns the UUID only when it's a real Xero post; otherwise null so the
 * receipt renders without the PDF panel.
 */
function _xeroInvoiceId(reference: string | null): string | null {
  if (!reference) return null;
  if (!reference.startsWith("xero:")) return null;
  const id = reference.slice("xero:".length);
  if (!/^[0-9a-fA-F-]{32,40}$/.test(id)) return null;
  return id;
}

const _PDF_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function InvoiceReceipt({ output }: { output: Json }) {
  const vendor = _str(output["vendor_name"]);
  const invoiceId = _str(output["invoice_id"]);
  const ref = _str(output["posting_reference"]);
  const url = _str(output["posting_url"]);
  const amount = _money(output["amount_total"], output["currency"]);
  const tax = output["tax_total"];
  const taxStr =
    tax != null && Number(tax) > 0 ? _money(tax, output["currency"]) : null;
  const validation = _str(output["validation_status"]);
  const approval = _str(output["approval_status"]);
  const posting = _str(output["posting_status"]);
  const provider = _str(output["posting_provider"]);
  const postingError = _str(output["posting_error"]);
  const xeroInvId = _xeroInvoiceId(ref);
  const pdfUrl = xeroInvId
    ? `${_PDF_BASE}/v1/integrations/xero/invoice/${xeroInvId}/pdf`
    : null;
  const isFailed = posting !== "POSTED" && (postingError || provider === "xero");
  // ``ref`` starts with ``gl_`` only when the routing GL adapter fell back
  // to the in-process stub — that means no Xero/QB connection produced a
  // real ledger entry. We surface that prominently so the user doesn't
  // mistake a green "Posted" pill for a real Xero invoice.
  const isStubMode =
    posting === "POSTED" && (ref ?? "").startsWith("gl_") && !xeroInvId;
  // line items for display
  type LineItem = { description?: string; qty?: number | string; unit_price?: number | string };
  const lineItems = (Array.isArray(output["line_items"])
    ? (output["line_items"] as LineItem[])
    : []
  ).filter((li) => li);

  return (
    <div
      className={`mt-3 rounded-md border p-3 ${
        isFailed
          ? "border-danger/50 bg-surface-elevated"
          : "border-success/40 bg-surface-elevated"
      }`}
    >
      <header className="flex items-center gap-2">
        <CheckCircle2
          className={`h-4 w-4 ${isFailed ? "text-text-danger" : "text-success"}`}
        />
        <span className="text-sm font-semibold text-text-primary">
          {isFailed
            ? "Invoice not posted"
            : `Invoice ${posting === "POSTED" ? "posted" : "processed"}`}
        </span>
        {posting === "POSTED" && !isFailed && !isStubMode ? (
          <span className="rounded-sm border border-success/40 bg-surface-blue px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-success">
            Live
          </span>
        ) : null}
        {isStubMode ? (
          <span className="rounded-sm border border-warning/40 bg-surface-blue px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-warning">
            Stub
          </span>
        ) : null}
        {isFailed ? (
          <span className="rounded-sm border border-danger/40 bg-surface-blue px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-text-danger">
            Failed
          </span>
        ) : null}
      </header>

      {isStubMode ? (
        <div className="mt-3 rounded-md border border-warning/40 bg-background p-2 text-xs text-text-secondary">
          <p className="font-mono text-[10px] uppercase tracking-wide text-warning">
            Stub mode — no real ledger
          </p>
          <p className="mt-1 leading-snug">
            This invoice has not been sent to Xero or QuickBooks. Connect an
            accounting integration in <span className="font-mono">Admin →
            Integrations</span> and re-post to record this in your real ledger.
          </p>
        </div>
      ) : null}

      {postingError ? (
        <div className="mt-3 rounded-md border border-danger/40 bg-background p-2 text-xs text-text-danger">
          <p className="font-mono text-[10px] uppercase tracking-wide opacity-70">
            {provider ? `${provider} rejection` : "Provider rejection"}
          </p>
          <p className="mt-1 leading-snug">{postingError}</p>
        </div>
      ) : null}

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
        {vendor ? (
          <>
            <dt className="font-mono uppercase tracking-wide text-text-muted">Vendor</dt>
            <dd className="font-medium text-text-primary">{vendor}</dd>
          </>
        ) : null}
        {amount ? (
          <>
            <dt className="font-mono uppercase tracking-wide text-text-muted">Amount</dt>
            <dd className="font-medium text-text-primary">
              {amount}
              {taxStr ? (
                <span className="ml-2 font-mono text-[11px] text-text-secondary">
                  (incl. tax {taxStr})
                </span>
              ) : null}
            </dd>
          </>
        ) : null}
        {invoiceId ? (
          <>
            <dt className="font-mono uppercase tracking-wide text-text-muted">Invoice ID</dt>
            <dd className="truncate font-mono text-[11px] text-text-primary">{invoiceId}</dd>
          </>
        ) : null}
        {ref ? (
          <>
            <dt className="font-mono uppercase tracking-wide text-text-muted">GL ref</dt>
            <dd className="truncate font-mono text-[11px] text-text-primary">{ref}</dd>
          </>
        ) : null}
      </dl>

      {lineItems.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-text-muted">
            Line items ({lineItems.length})
          </p>
          <ul className="space-y-1 text-xs">
            {lineItems.map((li, idx) => (
              <li key={idx} className="flex items-start justify-between gap-3 rounded-sm border border-border bg-background px-2 py-1">
                <span className="text-text-primary">
                  {li.description || "—"}
                </span>
                <span className="font-mono text-[11px] text-text-secondary whitespace-nowrap">
                  {String(li.qty ?? "1")} × {_money(li.unit_price, output["currency"]) ?? li.unit_price}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <StatusPill label="validation" value={validation} />
        <StatusPill label="approval" value={approval} />
        <StatusPill label="posting" value={posting} />
      </div>

      {pdfUrl ? (
        <div className="mt-3">
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-text-muted">
            Invoice PDF (live from Xero)
          </p>
          <iframe
            src={pdfUrl}
            title="Xero invoice PDF"
            className="h-[420px] w-full rounded-md border border-border bg-white"
          />
        </div>
      ) : null}

      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-background-5"
        >
          Open in Xero portal →
        </a>
      ) : null}
    </div>
  );
}

function GenericReceipt({ output }: { output: Json | null }) {
  if (!output) {
    return (
      <div className="mt-3 inline-flex items-center gap-1.5 rounded-sm border border-success/40 bg-surface-blue px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-success">
        Executed
      </div>
    );
  }
  // Pull a small, useful subset rather than dumping everything.
  const interesting = Object.entries(output).filter(([k, v]) => {
    if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) return false;
    if (typeof v === "object") return false;
    if (k === "tenant_id") return false;
    return true;
  });
  return (
    <div className="mt-3 rounded-md border border-success/40 bg-surface-elevated p-3">
      <header className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 text-success" />
        <span className="text-sm font-semibold text-text-primary">Executed</span>
      </header>
      {interesting.length ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
          {interesting.map(([k, v]) => (
            <Fragment key={k}>
              <dt className="font-mono uppercase tracking-wide text-text-muted">
                {k.replace(/_/g, " ")}
              </dt>
              <dd className="truncate font-mono text-[11px] text-text-primary">
                {String(v)}
              </dd>
            </Fragment>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function ExecutedReceipt({
  capability,
  result,
}: {
  capability: string;
  result: Json | null;
}) {
  // Backend envelope is { trace_id, agent_id, capabilities[], output: {...} }.
  // Some capabilities (read-only tools) flatten differently — fall back gracefully.
  const output =
    result && typeof result === "object" && "output" in result
      ? ((result as Json)["output"] as Json | null)
      : (result as Json | null);

  if (capability === "invoke_invoice_agent" && output) {
    return <InvoiceReceipt output={output} />;
  }
  return <GenericReceipt output={output} />;
}

function ProposalCard({
  b,
  onConfirm,
  onCancel,
}: {
  b: Extract<Bubble, { kind: "proposal" }>;
  onConfirm: (b: Extract<Bubble, { kind: "proposal" }>) => void;
  onCancel: (b: Extract<Bubble, { kind: "proposal" }>) => void;
}) {
  const argsPretty = JSON.stringify(b.args, null, 2);
  const expiresIn = (() => {
    const ms = new Date(b.expires_at).getTime() - Date.now();
    if (ms <= 0) return null;
    const sec = Math.floor(ms / 1000);
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  })();

  return (
    <div className="my-2 rounded-md border border-warning/50 border-l-[3px] border-l-warning bg-surface-elevated p-3">
      <header className="flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-sm border border-warning/60 bg-warning/10 text-warning">
          <ShieldCheck className="h-3.5 w-3.5" />
        </span>
        <div className="flex-1">
          <div className="text-sm font-semibold tracking-tight text-text-primary">
            Confirm write action
          </div>
          <div className="font-mono text-[11px] text-text-secondary">
            {b.capability}
          </div>
        </div>
        {b.state === "pending" && expiresIn ? (
          <span className="rounded-sm border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
            expires {expiresIn}
          </span>
        ) : null}
      </header>

      {/* Show inputs by default while pending; collapse after execution so
          the focus shifts to the receipt. */}
      <details className="mt-2 group" open={b.state === "pending"}>
        <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-wide text-text-muted hover:text-text-secondary">
          Inputs
        </summary>
        <pre className="mt-1 overflow-x-auto rounded-sm border border-border bg-surface p-2 font-mono text-[11px] text-text-primary">
          {argsPretty}
        </pre>
      </details>

      {b.state === "pending" ? (
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={() => onConfirm(b)}
            className="inline-flex items-center gap-1.5 rounded-md border border-navy-darker bg-navy px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-navy-dark"
          >
            <ShieldCheck className="h-3.5 w-3.5" /> Confirm
          </button>
          <button
            onClick={() => onCancel(b)}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-background-5"
          >
            Cancel
          </button>
        </div>
      ) : b.state === "confirming" ? (
        <div className="mt-3 flex items-center gap-2 font-mono text-[11px] uppercase tracking-wide text-text-secondary">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-navy border-t-transparent" />
          Executing…
        </div>
      ) : b.state === "executed" ? (
        <ExecutedReceipt capability={b.capability} result={b.result ?? null} />
      ) : b.state === "cancelled" ? (
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-sm border border-border bg-surface px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-text-secondary">
          Cancelled
        </div>
      ) : b.state === "expired" ? (
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-sm border border-warning/40 bg-surface px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-text-warning">
          Expired
        </div>
      ) : (
        <div className="mt-3 flex items-start gap-2 rounded-sm border border-danger bg-surface px-2 py-1.5 text-xs text-text-danger">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{b.error ?? "Failed"}</span>
        </div>
      )}
    </div>
  );
}

function BubbleView({
  b,
  onRate,
  onConfirm,
  onCancel,
}: {
  b: Bubble;
  onRate: (b: Bubble, r: 1 | -1) => void;
  onConfirm: (b: Extract<Bubble, { kind: "proposal" }>) => void;
  onCancel: (b: Extract<Bubble, { kind: "proposal" }>) => void;
}) {
  if (b.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-md border border-navy-darker bg-navy px-3 py-2 text-white">
          {b.text}
          {b.attachment ? (
            <div className="mt-1.5 flex items-center gap-1.5 rounded-sm border border-white/30 bg-white/10 px-2 py-1 text-[11px]">
              <FileText className="h-3 w-3" />
              <span className="truncate">{b.attachment.name}</span>
            </div>
          ) : null}
        </div>
      </div>
    );
  }
  if (b.kind === "error") {
    return (
      <div className="flex items-start gap-2 rounded-md border border-danger bg-surface-elevated px-3 py-2 text-xs text-text-danger">
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0">{b.text}</span>
      </div>
    );
  }
  if (b.kind === "action") return <AgentActionCard action={b.action} />;
  if (b.kind === "proposal") return <ProposalCard b={b} onConfirm={onConfirm} onCancel={onCancel} />;
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] space-y-1">
        <div className="rounded-md border border-border bg-surface-elevated px-3 py-2">
          {b.text ? (
            <Markdown text={b.text} />
          ) : b.streaming ? (
            <TypingDots />
          ) : null}
        </div>
        {b.messageId && b.text ? (
          <div className="flex items-center gap-3 px-1 text-text-muted">
            <button
              aria-label="Helpful"
              onClick={() => onRate(b, 1)}
              className={
                "transition-colors " +
                (b.rating === 1 ? "text-success" : "hover:text-text-secondary")
              }
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button
              aria-label="Not helpful"
              onClick={() => onRate(b, -1)}
              className={
                "transition-colors " +
                (b.rating === -1 ? "text-text-danger" : "hover:text-text-secondary")
              }
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
            <CopyButton text={b.text} />
            {b.rating ? (
              <span className="font-mono text-[10px] uppercase tracking-wide">
                Saved
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
