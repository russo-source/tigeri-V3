import { create } from "zustand";

type Toast = {
  id: string;
  title: string;
  message?: string;
  tone?: "success" | "info" | "warning" | "error";
};

type UiState = {
  sidebarOpen: boolean;
  pendingRequests: number;
  toasts: Toast[];
  setSidebarOpen: (open: boolean) => void;
  setPendingRequests: (count: number) => void;
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
};

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  pendingRequests: 0,
  toasts: [],
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setPendingRequests: (count) => set({ pendingRequests: count }),
  pushToast: (toast) =>
    set((state) => ({
      toasts: [
        ...state.toasts,
        {
          id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          ...toast,
        },
      ],
    })),
  dismissToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    })),
}));
