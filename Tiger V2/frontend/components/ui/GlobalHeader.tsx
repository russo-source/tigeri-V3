"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

interface GlobalHeaderProps {
  className?: string;
}

function readCurrentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  // The preflight script in app/layout.tsx applies .dark or .light to <html>
  // before paint. Read whatever it set so the toggle UI starts in sync.
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
  root.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem("theme", theme);
  } catch {
    /* private mode etc. */
  }
}

export default function GlobalHeader({ className = "" }: GlobalHeaderProps) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(readCurrentTheme());
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  };

  const isDark = theme === "dark";

  return (
    <header
      className={`border-b border-border bg-background/80 backdrop-blur ${className}`}
    >
      <div className="max-w-full mx-auto px-4 md:px-8">
        <div className="flex h-11 items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5">
            <Image
              src="/images/black-logo.svg"
              alt="Tigeri logo"
              width={28}
              height={28}
              className={`rounded-full ${isDark ? "hidden" : ""}`}
            />
            <Image
              src="/images/white-logo.svg"
              alt="Tigeri logo"
              width={28}
              height={28}
              className={`rounded-full ${isDark ? "" : "hidden"}`}
            />
            <span className="text-xl font-semibold tracking-tight text-text-primary">
              Tigeri
            </span>
          </Link>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle light and dark mode"
            aria-pressed={isDark}
            className="relative inline-flex h-8 w-14 items-center rounded-full border border-border bg-surface transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy focus-visible:ring-offset-2"
          >
            <span
              className="relative inline-flex h-6 w-6 transform items-center justify-center rounded-full border border-border bg-background transition-transform duration-150"
              style={{ transform: `translateX(${isDark ? 28 : 4}px)` }}
            >
              {isDark ? (
                <Moon className="h-4 w-4 text-text-primary" />
              ) : (
                <Sun className="h-4 w-4 text-text-primary" />
              )}
            </span>
          </button>
        </div>
      </div>
    </header>
  );
}
