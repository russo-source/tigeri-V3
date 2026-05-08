import { NextResponse } from "next/server";

import { isValidEmailFormat, sanitizeEmailInput } from "@/lib/input-validation";

type WaitlistPayload = {
  email?: string;
};

export async function POST(request: Request) {
  const webhookUrl =
    process.env.GOOGLE_SHEETS_WEBHOOK_URL ?? "https://script.google.com/macros/s/AKfycbxB9SReWP90_XA_mWLQbT_g5h_gdSFOWOU5m4zc6X10NiO-otTPPprtn1_qh_MNQurl/exec"
  if (!webhookUrl?.trim()) {
    return NextResponse.json(
      { message: "Waitlist integration is not configured yet." },
      { status: 500 }
    );
  }

  const body = (await request.json().catch(() => null)) as WaitlistPayload | null;
  const email = sanitizeEmailInput(body?.email ?? "");

  if (!isValidEmailFormat(email)) {
    return NextResponse.json(
      { message: "Please provide a valid email address." },
      { status: 400 }
    );
  }

  const payload = {
    email,
    timestamp: `${new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      timeZone: "Asia/Kolkata",
    }).format(new Date())} IST`,
  };

  try {
    const upstreamResponse = await fetch(webhookUrl.trim(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });

    if (!upstreamResponse.ok) {
      const upstreamText = await upstreamResponse.text().catch(() => "");
      return NextResponse.json(
        {
          message:
            upstreamText ||
            "Could not submit your request right now. Please try again shortly.",
        },
        { status: 502 }
      );
    }

    return NextResponse.json(
      { message: "Thanks! You have been added to the waitlist." },
      { status: 200 }
    );
  } catch {
    return NextResponse.json(
      { message: "Unable to reach waitlist service right now." },
      { status: 502 }
    );
  }
}
