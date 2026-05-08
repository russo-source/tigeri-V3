import { setTenantId, setUserId } from "./api";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ScopeResponse = {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  user_id: string;
  user_email: string;
  user_name: string;
  role: "owner" | "admin" | "member" | string;
  via: "cookie" | "header";
  must_change_password?: boolean;
};

export type SignUpInput = {
  tenant_name: string;
  email: string;
  name: string;
  password: string;
};

export type SignInInput = {
  tenant_slug: string;
  email: string;
  password: string;
};

class AuthApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const text = await res.text();
      try {
        const parsed = JSON.parse(text);
        detail = parsed.detail ?? parsed.error ?? parsed.message ?? text;
      } catch {
        detail = text || detail;
      }
    } catch {
      /* ignore */
    }
    throw new AuthApiError(res.status, String(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Mirror the cookie-resolved scope into localStorage so the legacy
 * header-auth path still works on routes we haven't migrated yet. */
function mirrorScopeToLocal(scope: ScopeResponse): void {
  setTenantId(scope.tenant_id);
  setUserId(scope.user_id);
}

export async function signUp(input: SignUpInput): Promise<ScopeResponse> {
  const scope = await postJson<ScopeResponse>("/auth/sign-up", input);
  mirrorScopeToLocal(scope);
  return scope;
}

export async function signIn(input: SignInInput): Promise<ScopeResponse> {
  const scope = await postJson<ScopeResponse>("/auth/sign-in", input);
  mirrorScopeToLocal(scope);
  return scope;
}

export async function signOut(): Promise<void> {
  await fetch(`${BASE_URL}/auth/sign-out`, {
    method: "POST",
    credentials: "include",
  });
}

export async function fetchMe(): Promise<ScopeResponse | null> {
  try {
    const res = await fetch(`${BASE_URL}/auth/me`, { credentials: "include" });
    if (res.status === 401 || res.status === 403) return null;
    if (!res.ok) return null;
    const scope = (await res.json()) as ScopeResponse;
    if (scope.via === "cookie") mirrorScopeToLocal(scope);
    return scope;
  } catch {
    return null;
  }
}

export function isAdmin(scope: ScopeResponse | null): boolean {
  return scope?.role === "owner" || scope?.role === "admin";
}
