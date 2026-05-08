"use client";

import { useEffect } from "react";
import Link from "next/link";
import Image from "next/image";
import { Moon, Sun } from "lucide-react";

interface GlobalHeaderProps {
  className?: string;
}

export default function GlobalHeader({ className = "" }: GlobalHeaderProps) {
  useEffect(() => {
    const root = document.documentElement;
    const storedTheme = window.localStorage.getItem("theme");
    const prefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;

    const initialTheme =
      storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : prefersDark
          ? "dark"
          : "light";

    root.classList.toggle("dark", initialTheme === "dark");
    root.classList.toggle("light", initialTheme === "light");
    root.setAttribute("data-theme", initialTheme);
  }, []);

  const toggleTheme = () => {
    const root = document.documentElement;
    const isCurrentlyDark = root.classList.contains("dark");
    const nextTheme = isCurrentlyDark ? "light" : "dark";

    root.classList.toggle("dark", nextTheme === "dark");
    root.classList.toggle("light", nextTheme === "light");
    root.setAttribute("data-theme", nextTheme);

    window.localStorage.setItem("theme", nextTheme);
  };

  return (
    <header className={`border-b border-border-10 backdrop-blur ${className}`}>
      <div className="max-w-full mx-auto px-4 md:px-8">
        <div className="flex h-11 items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5">
            <Image
              src="/images/black-logo.svg"
              alt="Tigeri logo"
              width={28}
              height={28}
              className="rounded-full dark:hidden"
            />
            <Image
              src="/images/white-logo.svg"
              alt="Tigeri logo"
              width={28}
              height={28}
              className="hidden rounded-full dark:block"
            />
            <span className="text-xl font-semibold tracking-tight text-text-primary">
              Tigeri
            </span>
          </Link>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle light and dark mode"
            className="relative inline-flex h-8 w-14 items-center rounded-full border border-border-10 bg-[#6e6e6e29] dark:bg-[#6e6e6e] transition-colors duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background-blue/60"
          >
            <span className="relative inline-flex h-6 w-6 translate-x-1 transform items-center justify-center rounded-full bg-background shadow transition-transform duration-300 dark:translate-x-7">
              <Moon className="absolute h-4 w-4 scale-0 opacity-0 text-text-primary transition-all duration-200 dark:scale-100 dark:opacity-100" />
              <Sun className="absolute h-4 w-4 scale-100 opacity-100 text-text-primary transition-all duration-200 dark:scale-0 dark:opacity-0" />
            </span>
          </button>

          {/* <div className="w-full max-w-[150px]">
            <label htmlFor="global-search" className="sr-only">
              Search
            </label>
            <input
              id="global-search"
              type="search"
              placeholder="Search..."
              className="h-11 w-full rounded-xs border-l border-border-10 px-4 text-sm text-text-primary outline-none placeholder:text-text-secondary focus:border-background-blue"
            />
          </div> */}
        </div>
      </div>
    </header>
  );
}
