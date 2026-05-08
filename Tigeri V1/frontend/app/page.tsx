"use client";

import Image from "next/image";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { joinWaitlist } from "@/lib/api";

const topStats = [
  {
    value: "$4.7T",
    text: "Lost annually to inefficient back-office processes globally.",
    note: "MCKINSEY 2025",
  },
  {
    value: "68%",
    text: "Of SME operators identify back-office admin as their primary operational bottleneck.",
    note: "",
  },
  {
    value: "40%",
    text: "Of SME staff time spent on repetitive admin that generates zero revenue.",
    note: "",
  },
];

const bottomStats = [
  {
    value: "$127K",
    text: "Average annual cost of a back-office role - replaceable at $499/mo",
  },
  {
    value: "3-5 days",
    text: "Average time to process a vendor invoice manually",
  },
  {
    value: "48 hrs",
    text: "Time to deploy any Tigeri agent - zero custom code",
  },
  {
    value: "70%+",
    text: "Gross margin at scale",
  },
];

const HERO_IMAGE_SRC = "/images/landing.png";

type WaitlistFormProps = {
  buttonStyle: "primary" | "light";
};

function WaitlistForm({ buttonStyle }: WaitlistFormProps) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "success">("idle");
  const [error, setError] = useState("");
  const waitlistMutation = useMutation({
    mutationFn: joinWaitlist,
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const normalizedEmail = email.trim().toLowerCase();

    if (!normalizedEmail) {
      setError("Please enter your work email.");
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(normalizedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }

    setError("");
    setStatus("success");
    setEmail("");

    void waitlistMutation.mutateAsync(normalizedEmail).catch(() => {
      // Keep optimistic success state visible even if network is flaky.
    });
  };

  if (status === "success") {
    return (
      <div
        className={`w-full rounded-xs border border-border-5 px-4 py-3 text-left text-base font-medium ${
          buttonStyle === "light"
            ? "bg-emerald-500/10 text-emerald-300"
            : "bg-emerald-500/10 text-emerald-300"
        }`}
      >
        Thanks! You have been added to the waitlist.
      </div>
    );
  }

  return (
    <>
      <form
        onSubmit={onSubmit}
        className="flex w-full flex-col gap-3 sm:flex-row sm:gap-2"
      >
        <input
          type="email"
          name="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Work email"
          autoComplete="email"
          required
          className="w-full rounded-xs border border-border-5 bg-surface px-4 py-2.5 text-base text-text-primary placeholder:text-text-muted focus:border-background-blue focus:outline-none"
        />
        <button
          type="submit"
          disabled={waitlistMutation.isPending}
          className={`rounded-xs border border-border-5 px-7 py-2.5 text-base font-semibold transition ${
            buttonStyle === "light"
              ? "bg-surface text-background-blue hover:bg-background-5"
              : "bg-background-blue text-white hover:bg-background-blue/90"
          } disabled:cursor-not-allowed disabled:opacity-70`}
        >
          {waitlistMutation.isPending ? "Submitting..." : "Join_Waitlist"}
        </button>
      </form>

      {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
    </>
  );
}

export default function HomePage() {
  return (
    <main className="min-h-screen bg-background text-text-primary">
      <header className="border-b border-border-5 bg-background-blue">
        <div className="mx-auto flex w-full max-w-full items-center justify-between px-4 py-3 md:px-8 lg:px-12 xl:px-16">
          <Link href="/" className="inline-flex items-center">
            <Image
              src="/images/white-logo.svg"
              alt="Tigeri"
              width={40}
              height={40}
              priority
              className=""
            />
          </Link>

          <button
            type="button"
            className="rounded-xs border border-border-5 bg-surface px-4 py-3 text-sm font-semibold text-background-blue sm:px-6"
          >
            Join Waitlist
          </button>
        </div>
      </header>

      <section className="mx-auto grid w-full max-w-full grid-cols-1 items-center gap-8 px-4 pb-14 pt-12 md:px-8 lg:grid-cols-2 lg:gap-0 lg:px-12 lg:pb-20 lg:pt-16 xl:px-16">
        <div className=" w-full justify-center flex lg:hidden">
          <Image
            src={HERO_IMAGE_SRC}
            alt="Tigeri product visual"
            width={400}
            height={400}
            priority
            className=" pr-10"
          />
        </div>

        <div className="space-y-5">
          <p className="text-xs font-semibold uppercase text-text-muted">
            <span className="mr-2 font-normal text-emerald-300">●</span>{" "}
            Accepting early access
          </p>

          <h1 className="text-3xl font-semibold leading-tight sm:text-4xl">
            The AI Operating System for{" "}
            <span className="text-background-blue">SME&apos;s</span>
          </h1>

          <p className="max-w-lg text-lg font-normal text-text-secondary sm:text-base">
            Integrated AI agents that replace your back-office. Invoice,
            expense, admin, staffing, booking, flight - deployed in 48 hours.
            Zero custom code.
          </p>

          <div className="max-w-lg">
            <WaitlistForm buttonStyle="primary" />
          </div>

          <p className="text-xs font-semibold uppercase text-text-muted">
            Live in 48 hours&nbsp;&nbsp;&nbsp; 6 core agents&nbsp;&nbsp;&nbsp; 8
            sectors
          </p>
        </div>

        <div className=" w-full justify-center hidden lg:flex">
          <Image
            src={HERO_IMAGE_SRC}
            alt="Tigeri product visual"
            width={500}
            height={500}
            priority
            className=""
          />
        </div>
      </section>

      <section className="mx-auto w-full max-w-full px-4 md:px-8 lg:px-12 xl:px-16">
        <div className="border-y border-border-5 py-12 sm:py-20">
          <p className="text-xs font-semibold uppercase text-text-muted">
            The Problem
          </p>
          <h2 className="mt-4 max-w-lg text-2xl font-semibold leading-tight">
            Manual operations are killing growth. The pain is real, measurable,
            and growing.
          </h2>

          <div className="mt-12 rounded-xs border border-border-5 bg-surface">
            <div className="grid grid-cols-1 md:grid-cols-3">
              {topStats.map((item, index) => (
                <div
                  key={item.value}
                  className={`border-border-5 p-6 sm:p-6 ${index !== 2 ? "md:border-r" : ""} ${index !== 0 ? "border-t md:border-t-0" : ""}`}
                >
                  <p className="text-4xl font-semibold text-background-blue">
                    {item.value}
                  </p>
                  <p className="mt-4 text-sm font-normal tracking-tighter text-text-secondary">
                    {item.text}
                  </p>
                  {item.note ? (
                    <p className="mt-4 text-xs font-semibold uppercase text-text-muted">
                      {item.note}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 border-t border-border-5 md:grid-cols-2 xl:grid-cols-4">
              {bottomStats.map((item, index) => (
                <div
                  key={item.value}
                  className={`border-border-5 p-6 text-center sm:p-6 ${index < 3 ? "xl:border-r" : ""} ${index === 1 ? "md:border-r xl:border-r" : ""} ${index > 0 ? "border-t md:border-t-0 xl:border-t-0" : ""}`}
                >
                  <p className="text-2xl font-semibold text-background-blue">
                    {item.value}
                  </p>
                  <p className="mt-2 text-xs font-normal text-text-secondary">
                    {item.text}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-full px-4 py-12 md:px-8 sm:py-16 lg:px-12 lg:py-20 xl:px-16">
        <div className="mx-auto max-w-245 rounded-xs border border-border-5 bg-background-blue px-5 py-12 text-center text-white sm:px-12 sm:py-12">
          <h3 className="text-3xl tracking-tight font-semibold">
            Replace your back-office. Not your team.
          </h3>
          <p className="mx-auto mt-4 max-w-lg font-normal text-base text-blue-200 sm:mt-6">
            Join the waitlist for early access. Select your vertical, select
            your agents, go live in 48 hours.
          </p>

          <div className="mx-auto mt-8 flex max-w-lg justify-center">
            <WaitlistForm buttonStyle="light" />
          </div>
        </div>
      </section>

      <footer className="mx-auto mt-auto w-full max-w-full border-t border-border-5 px-4 py-5 text-sm text-text-secondary md:px-8 lg:px-12 xl:px-16">
        <div className="flex flex-col items-start justify-between gap-4 font-normal lg:flex-row lg:items-center">
          <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:gap-4">
            <p>© 2026 Tigeri.ai. All rights reserved.</p>
            <div className="flex items-center gap-4">
              <Link
                href="/terms-conditions"
                className="font-medium hover:text-background-blue"
              >
                Terms
              </Link>
              <Link
                href="/privacy-policy"
                className="font-medium hover:text-background-blue"
              >
                Privacy
              </Link>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <p>
              Made by{" "}
              <a
                href="https://engxlab.com"
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold hover:text-background-blue"
              >
                Engxlab
              </a>
            </p>
          </div>
        </div>
      </footer>
    </main>
  );
}
