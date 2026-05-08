"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  CirclePlus,
  FileText,
  Home,
  LogOut,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import { logout } from "@/lib/api";
import type { SidebarUser } from "@/lib/type";

const MAX_EMAIL_LENGTH = 20;

function withDotsOnOverflow(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength)}...`;
}

const navItems = [
  {
    href: "/client-dashboard/home",
    label: "Home",
    icon: Home,
    tourId: "sidebar-nav-home",
  },
  {
    href: "/client-dashboard/integration",
    label: "Integrations",
    icon: CirclePlus,
    tourId: "sidebar-nav-integrations",
  },
  {
    href: "/client-dashboard/request-status",
    label: "Request Status",
    icon: FileText,
    tourId: "sidebar-nav-request-status",
  },
  {
    href: "/client-dashboard/new-agent",
    label: "New Agent",
    icon: Settings,
    tourId: "sidebar-nav-settings",
  },
  {
    href: "/client-dashboard/settings",
    label: "Settings",
    icon: SlidersHorizontal,
    tourId: "sidebar-nav-financial-settings",
  },
];

export default function SidebarNav({ user }: { user: SidebarUser }) {
  const pathname = usePathname();
  const router = useRouter();
  const displayEmail = withDotsOnOverflow(user.email, MAX_EMAIL_LENGTH);

  const handleLogout = async () => {
    await logout();
    router.replace("/sign-in");
  };

  return (
    <aside className="flex h-full min-h-0 w-64 shrink-0 flex-col border-r border-border-5 bg-surface">
      <nav className="flex-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              data-tour-id={item.tourId}
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

      <div className="border-t border-border-5 p-2">
        <div className="flex items-center gap-3 rounded-lg px-2 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-background-blue text-xs text-white">
            {user.initials}
          </div>
          <div>
            <p className="text-sm text-text-primary">{user.name}</p>
            <p className="text-xs text-text-muted" title={user.email}>
              {displayEmail}
            </p>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Logout"
            className="group ml-auto inline-flex items-center justify-center rounded-md text-text-muted transition-colors hover:text-text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background-blue/35"
          >
            <LogOut
              size={20}
              className="transition-transform group-hover:scale-110"
            />
          </button>
        </div>
      </div>
    </aside>
  );
}
