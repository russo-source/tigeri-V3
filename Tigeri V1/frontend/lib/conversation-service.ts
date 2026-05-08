import { API_ENDPOINTS } from "@/lib/api-endpoints";
import { apiRequest } from "@/lib/api";

export type ChannelType = "whatsapp" | "gmail" | "internal";

export type ConversationMessage = {
  id: string;
  userId: string;
  channel: ChannelType;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
};

export type ConversationSummary = {
  userId: string;
  summary: string;
  updatedAt: string;
};

export async function getConversationHistory(userId: string) {
  return apiRequest<{ messages: ConversationMessage[] }>(
    `${API_ENDPOINTS.conversation.history}?user_id=${encodeURIComponent(userId)}`,
    { auth: true }
  );
}

export async function getConversationSummary(userId: string) {
  return apiRequest<ConversationSummary>(API_ENDPOINTS.conversation.summarize, {
    method: "POST",
    auth: true,
    body: { user_id: userId },
  });
}

export async function upsertConversationEmbedding(userId: string, chunk: string) {
  return apiRequest<{ status: string }>(API_ENDPOINTS.conversation.embeddings, {
    method: "POST",
    auth: true,
    body: { user_id: userId, chunk },
  });
}

export async function syncConversationChannels(userId: string) {
  return apiRequest<{ status: string; channels: ChannelType[] }>(
    API_ENDPOINTS.conversation.channelSync,
    {
      method: "POST",
      auth: true,
      body: { user_id: userId },
    }
  );
}
