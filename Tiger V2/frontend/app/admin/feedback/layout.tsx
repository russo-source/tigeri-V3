"use client";

import { ReactNode } from "react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import SidebarNav from "@/components/client-dashboard/SidebarNav";
import IntegrationsBanner from "@/components/system/IntegrationsBanner";

// The parent /admin/layout.tsx already cookie-authenticates and role-gates
// (owner/admin only). This layout just provides the sidebar shell — adding
// another auth probe here would either duplicate the gate or, as it did
// previously, bounce cookie-authenticated admins to /sign-in on a fresh
// browser when the localStorage mirror hadn't populated yet.
export default function AdminFeedbackLayout({ children }: { children: ReactNode }) {
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
