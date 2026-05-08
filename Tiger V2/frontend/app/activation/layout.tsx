"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import GlobalHeader from "@/components/ui/GlobalHeader";
import FullPageLoader from "@/components/ui/full-page-loader";
import { getTenantId } from "@/lib/api";

export default function ActivationLayout({ children }: { children: ReactNode }) {
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
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">{children}</main>
    </div>
  );
}
