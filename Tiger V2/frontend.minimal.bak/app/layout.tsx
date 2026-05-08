import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Tigeri.ai",
  description: "Business automation platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-zinc-200 bg-white">
          <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4 text-sm">
            <Link href="/" className="font-semibold text-zinc-900">
              Tigeri.ai
            </Link>
            <Link href="/activation" className="text-zinc-700 hover:text-zinc-900">
              Activation
            </Link>
            <Link href="/agents" className="text-zinc-700 hover:text-zinc-900">
              Agents
            </Link>
            <Link href="/agents/invoice" className="text-zinc-700 hover:text-zinc-900">
              Invoice inbox
            </Link>
            <Link href="/audit" className="text-zinc-700 hover:text-zinc-900">
              Audit log
            </Link>
            <Link
              href="/sign-in"
              className="ml-auto text-zinc-700 hover:text-zinc-900"
            >
              Sign in
            </Link>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
