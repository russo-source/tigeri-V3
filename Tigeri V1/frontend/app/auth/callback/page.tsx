"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { bootstrapUserSession, setAccessToken } from "@/lib/api";
import FullPageLoader from "@/components/ui/full-page-loader";

function AuthCallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("access_token");

    async function completeOauth() {
      if (!token) {
        router.replace("/sign-in?error=oauth_failed");
        return;
      }

      try {
        setAccessToken(token);
        const { route } = await bootstrapUserSession();
        router.replace(route);
      } catch {
        router.replace("/sign-in?error=oauth_failed");
      }
    }

    void completeOauth();
  }, [router, searchParams]);

  return null;
}

function AuthCallbackFallback() {
  return (
    <FullPageLoader />
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<AuthCallbackFallback />}>
      <AuthCallbackHandler />
    </Suspense>
  );
}
