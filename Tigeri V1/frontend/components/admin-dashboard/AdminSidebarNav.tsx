"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  FileText,
  LayoutDashboard,
  LogOut,
  Logs,
  Settings,
  Shield,
  Users,
} from "lucide-react";
import { logout } from "@/lib/api";
import type { AdminNavItem, SidebarUser } from "@/lib/type";

const MAX_EMAIL_LENGTH = 20;

function withDotsOnOverflow(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength)}...`;
}

function getIcon(icon: AdminNavItem["icon"]) {
  switch (icon) {
    case "dashboard":
      return LayoutDashboard;
    case "requests":
      return FileText;
    case "clients":
      return Users;
    case "monitoring":
      return Activity;
    case "logs":
      return Logs;
    case "settings":
      return Settings;
    case "shield":
      return Shield;
    default:
      return LayoutDashboard;
  }
}

export default function AdminSidebarNav({
  user,
  navItems,
}: {
  user: SidebarUser;
  navItems: AdminNavItem[];
}) {
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
          const Icon = getIcon(item.icon);
          const isActive = pathname === item.href;

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
