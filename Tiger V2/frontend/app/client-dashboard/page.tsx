"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ClientDashboardPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/client-dashboard/home");
  }, [router]);
  return null;
}
