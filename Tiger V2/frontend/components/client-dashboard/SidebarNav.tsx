"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  FileText,
  Home,
  LogOut,
  MessageSquare,
  Plug,
  Receipt,
  ShieldCheck,
} from "lucide-react";
import { clearSession, getTenantId, getUserId } from "@/lib/api";

const MAX_EMAIL_LENGTH = 24;

function withDots(value: string, max: number) {
  return value.length <= max ? value : `${value.slice(0, max)}...`;
}

const navItems = [
  { href: "/client-dashboard/home", label: "Agents", icon: Home },
  { href: "/activation", label: "Activation", icon: ShieldCheck },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/agents/invoice", label: "Invoice inbox", icon: Receipt },
  { href: "/audit", label: "Audit log", icon: FileText },
  { href: "/admin/feedback", label: "Chat feedback", icon: MessageSquare },
];

export default function SidebarNav() {
  const pathname = usePathname();
  const router = useRouter();

  const tenantId = getTenantId() ?? "—";
  const userId = getUserId();
  const initial = (userId ?? "?").slice(0, 1).toUpperCase();

  const handleLogout = () => {
    clearSession();
    router.replace("/sign-in");
  };

  return (
    <aside className="flex h-full min-h-0 w-64 shrink-0 flex-col border-r border-border bg-surface">
      <nav className="flex-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2 px-9 py-3 text-sm transition-colors ${
                isActive
                  ? "bg-background-5 text-text-primary"
                  : "text-text-secondary hover:bg-background-5"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-2">
        <div className="flex items-center gap-3 rounded-md px-2 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-navy-darker bg-navy text-xs text-white">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-text-primary">{userId}</p>
            <p className="truncate text-xs text-text-muted" title={tenantId}>
              {withDots(tenantId, MAX_EMAIL_LENGTH)}
            </p>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Sign out"
            className="group ml-auto inline-flex items-center justify-center rounded-md text-text-muted transition-colors hover:text-text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy"
          >
            <Activity className="hidden h-4 w-4" />
            <LogOut size={20} className="transition-transform group-hover:scale-110" />
          </button>
        </div>
      </div>
    </aside>
  );
}
