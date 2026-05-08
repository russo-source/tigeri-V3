import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getRedirectForRoute } from "@/lib/middleware/route-guard-policy";

const ACCESS_TOKEN_COOKIE = "auth_access_token";
const USER_ROLE_COOKIE = "auth_user_role";

export function middleware(request: NextRequest) {
  const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  const role = request.cookies.get(USER_ROLE_COOKIE)?.value;
  const pathname = request.nextUrl.pathname;

  const redirectPath = getRedirectForRoute({
    pathname,
    hasToken: Boolean(token),
    role: role === "admin" || role === "client" ? role : undefined,
  });

  if (redirectPath) {
    return NextResponse.redirect(new URL(redirectPath, request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
