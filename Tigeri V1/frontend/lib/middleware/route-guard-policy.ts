export type UserRole = "admin" | "client" | undefined;

const protectedPrefixes = ["/admin-dashboard", "/client-dashboard", "/onboarding"];
const guestOnlyRoutes = ["/sign-in", "/sign-up", "/forgot-password", "/reset-password"];

function isProtectedPath(pathname: string) {
  return protectedPrefixes.some((prefix) => pathname.startsWith(prefix));
}

function isGuestOnlyPath(pathname: string) {
  return guestOnlyRoutes.some((route) => pathname === route);
}

export function getRedirectForRoute(params: {
  pathname: string;
  hasToken: boolean;
  role: UserRole;
}): string | null {
  const { pathname, hasToken, role } = params;

  if (!hasToken && isProtectedPath(pathname)) {
    return `/sign-in?redirect=${encodeURIComponent(pathname)}`;
  }

  if (hasToken && isGuestOnlyPath(pathname)) {
    return role === "admin" ? "/admin-dashboard/dashboard" : "/request-status";
  }

  if (hasToken && pathname.startsWith("/admin-dashboard") && role && role !== "admin") {
    return "/request-status";
  }

  if (hasToken && pathname.startsWith("/client-dashboard") && role === "admin") {
    return "/admin-dashboard/dashboard";
  }

  if (hasToken && pathname.startsWith("/onboarding") && role === "admin") {
    return "/admin-dashboard/dashboard";
  }

  return null;
}

export function readAuthFromCookies(cookieString: string) {
  const pairs = cookieString
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean);

  const entries = new Map<string, string>();
  for (const pair of pairs) {
    const index = pair.indexOf("=");
    if (index <= 0) continue;
    const key = pair.slice(0, index);
    const value = decodeURIComponent(pair.slice(index + 1));
    entries.set(key, value);
  }

  const token = entries.get("auth_access_token") ?? "";
  const role = (entries.get("auth_user_role") as UserRole) ?? undefined;

  return {
    hasToken: Boolean(token),
    role,
  };
}
