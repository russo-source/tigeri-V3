"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import SidebarNav from "@/components/client-dashboard/SidebarNav";
import {
  getCachedResolvedRoute,
  getClientActiveAgents,
  getCurrentUser,
  setCachedResolvedRoute,
  streamClientSystemStatus,
  toSidebarUser,
} from "@/lib/api";
import type { SidebarUser } from "@/lib/type";
import GlobalHeader from "@/components/ui/GlobalHeader";
import ClientDashboardTourProvider from "@/components/client-dashboard/ClientDashboardTourProvider";
import { ClientDashboardLayoutSkeleton } from "@/components/ui/skeletons";
import {
  getRedirectForRoute,
  readAuthFromCookies,
} from "@/lib/middleware/route-guard-policy";

export default function ClientDashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<SidebarUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [isApproved, setIsApproved] = useState(false);
  const [maintenance, setMaintenance] = useState<{
    active: boolean;
    until?: string;
  }>({ active: false });

  useEffect(() => {
    const cookieAuth = readAuthFromCookies(document.cookie);
    const manualRedirect = getRedirectForRoute({
      pathname: "/client-dashboard",
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

        if (currentUser.is_admin) {
          setCachedResolvedRoute("/admin-dashboard/dashboard");
          setLoading(false);
          router.replace("/admin-dashboard/dashboard");
          return;
        }

        const cachedRoute = getCachedResolvedRoute();
        if (cachedRoute === "/client-dashboard/home") {
          setUser(toSidebarUser(currentUser));
          setIsApproved(true);
          setLoading(false);
          return;
        }
        if (cachedRoute) {
          setLoading(false);
          router.replace(cachedRoute);
          return;
        }

        let agentStatus = "pending";
        try {
          const res = await getClientActiveAgents();
          agentStatus = res.status;
        } catch {
          if (!currentUser.client_id) {
            setLoading(false);
            router.replace("/onboarding");
            return;
          }
          setLoading(false);
          router.replace("/request-status");
          return;
        }

        setUser(toSidebarUser(currentUser));

        if (agentStatus !== "approved") {
          setCachedResolvedRoute("/request-status");
          setIsApproved(false);
          setLoading(false);
          router.replace("/request-status");
          return;
        }
        setCachedResolvedRoute("/client-dashboard/home");
        setIsApproved(true);
      } catch {
        setLoading(false);
        router.replace("/sign-in");
      } finally {
        setLoading(false);
      }
    }
    void guardRoute();
  }, [router]);

  // fetch-based SSE
  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout>;
    let stopStream: (() => void) | null = null;

    async function connect() {
      stopStream?.();
      stopStream = streamClientSystemStatus(
        (data) => {
          setMaintenance({
            active: data.maintenance_mode,
            until: data.maintenance_until,
          });
        },
        () => {
          retryTimeout = setTimeout(() => void connect(), 5000);
        },
      );
    }

    void connect();

    return () => {
      clearTimeout(retryTimeout);
      stopStream?.();
    };
  }, []);

  if (loading) {
    return <ClientDashboardLayoutSkeleton />;
  }

  return (
    <ClientDashboardTourProvider>
      <main className="flex h-screen min-h-0 flex-col overflow-hidden text-text-primary">
        <GlobalHeader className="shrink-0" />
        <div className="flex min-h-0 flex-1 overflow-hidden border-t border-border-5">
          {isApproved && user && <SidebarNav user={user} />}
          <section className="min-w-0 flex-1 overflow-y-auto overscroll-contain border-l border-border-5 bg-background-dashboard">
            {maintenance.active ? (
              <div className="tag-warning border-b border-border-5 px-5 py-2 text-sm">
                System is under maintenance.
                {maintenance.until
                  ? ` Expected back at ${new Date(maintenance.until).toLocaleString()}.`
                  : " We will be back shortly."}
              </div>
            ) : null}
            <div className="p-5">{children}</div>
          </section>
        </div>
      </main>
    </ClientDashboardTourProvider>
  );
}
