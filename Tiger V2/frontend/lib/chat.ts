import { getSessionId, getTenantId, getUserId } from "./api";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type HistoryAction = {
  kind: "tool_running" | "tool_done" | "agent_run";
  tool?: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  agent_id?: string;
  capabilities?: string[];
  trace_id?: string;
};

export type HistoryMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: HistoryAction[];
  created_at: string;
};

export type HistoryResponse = {
  thread_id: string | null;
  messages: HistoryMessage[];
};

export type ChatEvent =
  | { type: "assistant_message_id"; id: string }
  | { type: "agent_text"; content: string; delta?: boolean }
  | { type: "tool_call"; id: string; tool: string; args: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      ok: boolean;
      result: Record<string, unknown> | unknown[];
    }
  | {
      type: "agent_run";
      agent_id: string;
      capabilities: string[];
      trace_id: string;
      summary: string;
    }
  | {
      type: "tool_proposed";
      tool_use_id?: string;
      action_id: string;
      capability: string;
      args: Record<string, unknown>;
      diff_snapshot: Record<string, unknown>;
      confirmation_token: string;
      expires_at: string;
    }
  | { type: "done" }
  | { type: "error"; message: string };

export type ActionResponse = {
  id: string;
  capability: string;
  status: "pending" | "confirmed" | "executed" | "expired" | "cancelled" | "failed";
  confirmed_at: string | null;
  executed_at: string | null;
  result: Record<string, unknown> | null;
  error_detail: string | null;
};

function tenantHeaders(): Record<string, string> | null {
  const tenantId = getTenantId();
  if (!tenantId) return null;
  return {
    "X-Tigeri-Tenant-Id": tenantId,
    "X-Tigeri-User-Id": getUserId(),
    "X-Tigeri-Session-Id": getSessionId(),
  };
}

export async function loadHistory(): Promise<HistoryResponse> {
  const headers = tenantHeaders();
  if (!headers) return { thread_id: null, messages: [] };
  const res = await fetch(`${BASE_URL}/chat/history`, {
    headers,
    credentials: "include",
  });
  if (!res.ok) return { thread_id: null, messages: [] };
  return (await res.json()) as HistoryResponse;
}

export async function clearHistory(): Promise<{ cleared: boolean; messages_deleted: number }> {
  const headers = tenantHeaders();
  if (!headers) return { cleared: false, messages_deleted: 0 };
  const res = await fetch(`${BASE_URL}/chat/history`, {
    method: "DELETE",
    headers,
    credentials: "include",
  });
  if (!res.ok) return { cleared: false, messages_deleted: 0 };
  return (await res.json()) as { cleared: boolean; messages_deleted: number };
}

export type UploadedFile = {
  filename: string;
  media_type: string;
  char_count: number;
  truncated: boolean;
  text: string;
};

export async function uploadFile(file: File): Promise<UploadedFile> {
  const headers = tenantHeaders();
  if (!headers) throw new Error("no tenant id — sign in first");
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/chat/upload`, {
    method: "POST",
    headers, // do NOT set Content-Type — browser must set multipart boundary
    body: form,
    credentials: "include",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Upload failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as UploadedFile;
}

export async function confirmAction(
  confirmation_token: string,
): Promise<ActionResponse> {
  const headers = tenantHeaders();
  if (!headers) throw new Error("no tenant id — sign in first");
  const res = await fetch(`${BASE_URL}/actions/confirm`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation_token }),
    credentials: "include",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Confirm failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as ActionResponse;
}

export async function cancelAction(
  confirmation_token: string,
): Promise<ActionResponse> {
  const headers = tenantHeaders();
  if (!headers) throw new Error("no tenant id — sign in first");
  const res = await fetch(`${BASE_URL}/actions/cancel`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation_token }),
    credentials: "include",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Cancel failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as ActionResponse;
}

export async function sendFeedback(
  message_id: string,
  rating: 1 | -1,
  comment = "",
): Promise<void> {
  const headers = tenantHeaders();
  if (!headers) return;
  await fetch(`${BASE_URL}/chat/feedback`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ message_id, rating, comment }),
    credentials: "include",
  });
}

export async function streamChat(
  message: string,
  history: ChatTurn[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = tenantHeaders();
  if (!headers) {
    onEvent({ type: "error", message: "no tenant id — sign in first" });
    return;
  }
  const res = await fetch(`${BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
    signal,
    credentials: "include",
  });

  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `HTTP ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.startsWith("data: ") ? part.slice(6) : part;
      if (!line.trim()) continue;
      try {
        const ev = JSON.parse(line) as ChatEvent;
        onEvent(ev);
        if (ev.type === "done" || ev.type === "error") return;
      } catch {
        /* swallow */
      }
    }
  }
}
