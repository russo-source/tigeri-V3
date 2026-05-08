"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Eye, EyeOff } from "lucide-react";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";
import {
  bootstrapUserSession,
  googleLoginUrl,
  setAccessToken,
  signInWithEmail,
} from "@/lib/api";
import {
  isValidEmailFormat,
  sanitizeEmailInput,
  sanitizeSecretLike,
} from "@/lib/input-validation";
import { useAuthStore } from "@/lib/stores/auth-store";
import {
  getRedirectForRoute,
  readAuthFromCookies,
} from "@/lib/middleware/route-guard-policy";

export default function SignInPage() {
  const router = useRouter();
  const setAuthenticatedUser = useAuthStore(
    (state) => state.setAuthenticatedUser,
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const signInMutation = useMutation({
    mutationFn: async () => {
      const result = await signInWithEmail(email, password);
      if (result.access_token) {
        setAccessToken(result.access_token);
      }
      const session = await bootstrapUserSession();
      return session;
    },
  });

  useEffect(() => {
    const cookieAuth = readAuthFromCookies(document.cookie);
    const redirectPath = getRedirectForRoute({
      pathname: "/sign-in",
      hasToken: cookieAuth.hasToken,
      role: cookieAuth.role,
    });

    if (redirectPath) {
      router.replace(redirectPath);
    }
  }, [router]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (!isValidEmailFormat(email)) {
      window.alert("Please enter a valid email address.");
      setError("Please enter a valid email address.");
      return;
    }

    try {
      const { route, user } = await signInMutation.mutateAsync();
      setAuthenticatedUser(user, route);
      router.replace(route);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    }
  };

  const onGoogleClick = () => {
    window.location.href = googleLoginUrl();
  };

  return (
    <main className="flex min-h-screen flex-col bg-background text-text-primary">
      <GlobalHeader />

      <section className="max-w-full mx-auto flex w-full flex-1">
        <div className="grid w-full gap-5 lg:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="p-6 shadow-sm md:p-16 flex flex-col justify-center"
          >
            <h1 className="text-4xl font-semibold tracking-tight text-text-primary">
              Sign into <br />
              Tigeri Platform
            </h1>

            <form className="mt-7 space-y-4" onSubmit={onSubmit}>
              <motion.button
                type="button"
                onClick={onGoogleClick}
                whileHover={{ y: -2 }}
                className="flex w-full items-center justify-center rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base font-medium text-text-secondary"
              >
                <svg
                  className="mr-3 h-5 w-5"
                  viewBox="0 0 18 18"
                  aria-hidden
                  focusable="false"
                >
                  <path
                    fill="#4285F4"
                    d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.56 2.68-3.86 2.68-6.62z"
                  />
                  <path
                    fill="#34A853"
                    d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M3.97 10.72A5.41 5.41 0 0 1 3.7 9c0-.6.1-1.2.27-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.82.96 4.05l3.01-2.33z"
                  />
                  <path
                    fill="#EA4335"
                    d="M9 3.58c1.32 0 2.5.46 3.43 1.35l2.58-2.58A8.94 8.94 0 0 0 9 0a9 9 0 0 0-8.04 4.95l3.01 2.33c.71-2.12 2.7-3.7 5.03-3.7z"
                  />
                </svg>
                Continue With Google
              </motion.button>

              <div className="border-t border-border-5 pt-4" />

              <label className="block text-sm font-medium text-text-secondary">
                Email
                <input
                  type="email"
                  required
                  maxLength={254}
                  value={email}
                  onChange={(e) => setEmail(sanitizeEmailInput(e.target.value))}
                  onBlur={() => {
                    if (email && !isValidEmailFormat(email)) {
                      window.alert("Please enter a valid email address.");
                    }
                  }}
                  placeholder="you@company.com"
                  className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
                />
              </label>

              <label className="block text-sm font-medium text-text-secondary">
                <span className="flex items-center justify-between">
                  Password
                  <Link
                    href="/forgot-password"
                    className="text-xs text-text-muted hover:text-text-primary"
                  >
                    Forgot password?
                  </Link>
                </span>
                <div className="relative mt-2">
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={8}
                    maxLength={128}
                    value={password}
                    onChange={(e) =>
                      setPassword(sanitizeSecretLike(e.target.value, 128))
                    }
                    placeholder="Enter password"
                    className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 pr-11 text-base text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-text-muted"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>

              {error ? (
                <p className="text-sm text-text-danger">{error}</p>
              ) : null}

              <label className="flex items-center gap-2 text-sm text-text-secondary">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border"
                />
                Remember me
              </label>

              <motion.button
                type="submit"
                disabled={signInMutation.isPending}
                whileHover={{ y: -2 }}
                whileTap={{ scale: 0.99 }}
                className="w-full rounded-xs bg-background-blue px-4 py-3 text-base font-semibold text-white shadow-[0_8px_20px_rgba(53,55,215,0.28)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {signInMutation.isPending ? "Signing in..." : "Sign in"}
              </motion.button>
            </form>

            <p className="mt-6 text-center text-sm text-text-muted">
              Don&apos;t have an account?{" "}
              <Link
                href="/sign-up"
                className="font-semibold text-background-blue hover:underline"
              >
                Sign up
              </Link>
            </p>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, ease: "easeOut", delay: 0.05 }}
            className="relative hidden overflow-hidden lg:block"
          >
            <Image
              src="/images/loginbg.svg"
              alt="Tigeri platform preview"
              fill
              priority
              className="object-cover"
            />
          </motion.section>
        </div>
      </section>

      <GlobalFooter />
    </main>
  );
}
