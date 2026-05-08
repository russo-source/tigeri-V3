"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import GlobalHeader from "@/components/ui/GlobalHeader";
import SidebarNav from "@/components/client-dashboard/SidebarNav";
import FullPageLoader from "@/components/ui/full-page-loader";
import IntegrationsBanner from "@/components/system/IntegrationsBanner";
import { getTenantId } from "@/lib/api";

export default function IntegrationsLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!getTenantId()) {
      router.replace("/sign-in");
      return;
    }
    setReady(true);
  }, [router]);
  if (!ready) return <FullPageLoader />;
  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden text-text-primary">
      <GlobalHeader className="shrink-0" />
      <IntegrationsBanner />
      <div className="flex min-h-0 flex-1 overflow-hidden border-t border-border-5">
        <SidebarNav />
        <section className="min-w-0 flex-1 overflow-y-auto border-l border-border-5 bg-background-dashboard">
          <div className="p-5">{children}</div>
        </section>
      </div>
    </main>
  );
}
