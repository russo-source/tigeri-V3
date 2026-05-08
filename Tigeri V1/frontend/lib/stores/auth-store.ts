import { create } from "zustand";

import type { CurrentUser } from "@/lib/type";

type AuthState = {
  isAuthenticated: boolean;
  user: CurrentUser | null;
  resolvedRoute: string | null;
  setAuthenticatedUser: (user: CurrentUser, route: string) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  user: null,
  resolvedRoute: null,
  setAuthenticatedUser: (user, route) =>
    set({
      isAuthenticated: true,
      user,
      resolvedRoute: route,
    }),
  clearSession: () =>
    set({
      isAuthenticated: false,
      user: null,
      resolvedRoute: null,
    }),
}));
