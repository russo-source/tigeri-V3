"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import FullPageLoader from "@/components/ui/full-page-loader";
import { fetchMe, isAdmin, type ScopeResponse } from "@/lib/auth";

/** Role gate for /admin/*. Composes with any child layouts (e.g.
 * /admin/feedback/layout.tsx still provides the sidebar shell).
 *
 * Resolution order:
 *   1. fetch /auth/me to check whether the current cookie/header session
 *      belongs to a user with role 'owner' or 'admin'.
 *   2. If not, redirect to /sign-in.
 *   3. If 401, redirect to /sign-in.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [scope, setScope] = useState<ScopeResponse | null | "loading">("loading");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const me = await fetchMe();
      if (cancelled) return;
      if (!me) {
        router.replace("/sign-in");
        return;
      }
      if (!isAdmin(me)) {
        router.replace("/client-dashboard/home");
        return;
      }
      setScope(me);
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (scope === "loading" || scope === null) return <FullPageLoader label="Verifying admin access" />;
  return <>{children}</>;
}
