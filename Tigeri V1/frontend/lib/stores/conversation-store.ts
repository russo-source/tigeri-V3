import { create } from "zustand";

import type { ChannelType, ConversationMessage, ConversationSummary } from "@/lib/conversation-service";

type ConversationState = {
  activeChannel: ChannelType;
  messages: ConversationMessage[];
  summary: ConversationSummary | null;
  setActiveChannel: (channel: ChannelType) => void;
  setMessages: (messages: ConversationMessage[]) => void;
  appendMessage: (message: ConversationMessage) => void;
  setSummary: (summary: ConversationSummary) => void;
  reset: () => void;
};

const initialState = {
  activeChannel: "internal" as ChannelType,
  messages: [],
  summary: null,
};

export const useConversationStore = create<ConversationState>((set) => ({
  ...initialState,
  setActiveChannel: (channel) => set({ activeChannel: channel }),
  setMessages: (messages) => set({ messages }),
  appendMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),
  setSummary: (summary) => set({ summary }),
  reset: () => set(initialState),
}));
