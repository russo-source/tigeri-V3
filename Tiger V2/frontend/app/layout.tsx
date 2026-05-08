import type { Metadata } from "next";
import ChatLauncher from "@/components/chat/ChatLauncher";
import "./globals.css";

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

// Resolves the theme synchronously, before paint, so the toggle in GlobalHeader
// doesn't cause a flash of the wrong scheme on cold load.
const themePreflight = `(function(){try{var s=localStorage.getItem('theme');var t=(s==='dark'||s==='light')?s:(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');var r=document.documentElement;r.classList.add(t);r.setAttribute('data-theme',t);}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
        <script dangerouslySetInnerHTML={{ __html: themePreflight }} />
      </head>
      <body className="min-h-full flex flex-col">
        {children}
        <ChatLauncher />
      </body>
    </html>
  );
}
