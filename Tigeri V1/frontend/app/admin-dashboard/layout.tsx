"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AdminSidebarNav from "@/components/admin-dashboard/AdminSidebarNav";
import {
  getCachedResolvedRoute,
  getAdminNavItems,
  getCurrentUser,
  resolveUserRoute,
  setCachedResolvedRoute,
  toAdminSidebarUser,
} from "@/lib/api";
import type { AdminNavItem, SidebarUser } from "@/lib/type";
import GlobalHeader from "@/components/ui/GlobalHeader";
import { AdminDashboardLayoutSkeleton } from "@/components/ui/skeletons";
import {
  getRedirectForRoute,
  readAuthFromCookies,
} from "@/lib/middleware/route-guard-policy";

export default function AdminDashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const navItems = useMemo<AdminNavItem[]>(() => getAdminNavItems(), []);
  const [user, setUser] = useState<SidebarUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const cookieAuth = readAuthFromCookies(document.cookie);
    const manualRedirect = getRedirectForRoute({
      pathname: "/admin-dashboard",
      hasToken: cookieAuth.hasToken,
      role: cookieAuth.role,
    });

    if (manualRedirect) {
      router.replace(manualRedirect);
      setLoading(false);
      return;
    }

    async function guardRoute() {
      try {
        const currentUser = await getCurrentUser();

        if (!currentUser.is_admin) {
          const cachedRoute = getCachedResolvedRoute();
          if (cachedRoute) {
            router.replace(cachedRoute);
            return;
          }
          router.replace(await resolveUserRoute(currentUser));
          return;
        }

        setCachedResolvedRoute("/admin-dashboard/dashboard");
        setUser(toAdminSidebarUser(currentUser));
      } catch {
        router.replace("/sign-in");
      } finally {
        setLoading(false);
      }
    }

    void guardRoute();
  }, [router]);

  if (loading || !user) {
    return <AdminDashboardLayoutSkeleton />;
  }

  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-background text-text-primary">
      <GlobalHeader className="shrink-0" />
      <div className="flex min-h-0 flex-1 overflow-hidden border-t border-border-5">
        <AdminSidebarNav user={user} navItems={navItems} />
        <section className="min-w-0 flex-1 overflow-y-auto overscroll-contain border-l border-border-5 bg-background-dashboard">
          <div className="p-5">{children}</div>
        </section>
      </div>
    </main>
  );
}
