import type { Metadata } from "next";
import "./globals.css";
import AppProviders from "@/app/providers";

export const metadata: Metadata = {
  metadataBase: new URL("https://tigeri.ai"),
  title: {
    default: "Tigeri | AI Agent Platform",
    template: "%s | Tigeri",
  },
  description:
    "Tigeri helps teams onboard, deploy, and manage AI agents with secure workflows and role-based dashboards.",
  applicationName: "Tigeri",
  keywords: [
    "Tigeri",
    "AI agents",
    "agent management",
    "workflow automation",
    "dashboard",
    "business automation",
  ],
  authors: [{ name: "Tigeri" }],
  creator: "Tigeri",
  publisher: "Tigeri",
  robots: {
    index: true,
    follow: true,
  },
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon.ico",
    apple: "/favicon.ico",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://tigeri.ai",
    siteName: "Tigeri",
    title: "Tigeri | AI Agent Platform",
    description:
      "Onboard and operate AI agents with secure, scalable tools built for modern teams.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Tigeri | AI Agent Platform",
    description:
      "Onboard and operate AI agents with secure, scalable tools built for modern teams.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full font-medium antialiased dark"
      data-theme="dark"
    >
      <body className="min-h-full flex flex-col">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
