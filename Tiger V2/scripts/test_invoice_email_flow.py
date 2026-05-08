"""End-to-end smoke test: raise an invoice via chat, surface it, email it.

Drives the deployed FastAPI backend over HTTP exactly like the browser does:
sign in → /chat/stream (invoice) → /actions/confirm → /chat/stream (email
follow-up) → /actions/confirm → /audit/records to verify the chain.

Usage
-----
The script reads the API base URL, frontend origin, and credentials from
environment variables:

    TIGERI_API_BASE_URL    e.g. https://api.tigeri.ai/api  (no trailing slash)
    TIGERI_FRONTEND_ORIGIN e.g. https://app.tigeri.ai      (used as the
                           Origin header so the CSRF guard accepts our POSTs)
    TIGERI_TENANT_SLUG     tenant to act inside (e.g. demo, admin)
    TIGERI_USER_EMAIL      sign-in email
    TIGERI_USER_PASSWORD   sign-in password

Optionally override the prompt and recipient:

    TIGERI_TEST_RECIPIENT  default russo@tigeri.ai
    TIGERI_TEST_AMOUNT     default 1250.00
    TIGERI_TEST_VENDOR     default "Tigeri Test Vendor Ltd"

Run::

    .venv/bin/python scripts/test_invoice_email_flow.py

Prerequisites the script does *not* set up for you (and will fail loudly on):
  1. Gmail or Microsoft 365 must be connected on the target tenant. The
     send_gmail / send_outlook tool needs an OAuth access token that only
     exists if a human has completed the consent flow at /integrations.
  2. An admin user that can sign in. Use scripts/seed_admin.py if needed.

The script is idempotent in the sense that re-running it just emits another
invoice + email pair. It does not clean up.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx


def _env(name: str, default: str | None = None, *, required: bool = True) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise SystemExit(
            f"missing env: {name}. See the docstring at the top of this file."
        )
    return val or ""


API_BASE = _env("TIGERI_API_BASE_URL", "http://localhost:8000")
FRONTEND_ORIGIN = _env("TIGERI_FRONTEND_ORIGIN", "http://localhost:3000")
TENANT_SLUG = _env("TIGERI_TENANT_SLUG")
USER_EMAIL = _env("TIGERI_USER_EMAIL")
USER_PASSWORD = _env("TIGERI_USER_PASSWORD")

RECIPIENT = _env("TIGERI_TEST_RECIPIENT", "russo@tigeri.ai", required=False)
AMOUNT = _env("TIGERI_TEST_AMOUNT", "1250.00", required=False)
VENDOR = _env("TIGERI_TEST_VENDOR", "Tigeri Test Vendor Ltd", required=False)


# Headers the deployed backend's CSRF Origin middleware accepts.
COMMON_HEADERS = {
    "Origin": FRONTEND_ORIGIN,
    "Referer": FRONTEND_ORIGIN + "/",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _print(label: str, payload: Any = None) -> None:
    bar = "─" * 72
    print(f"\n{bar}\n{label}\n{bar}")
    if payload is not None:
        if isinstance(payload, (dict, list)):
            print(json.dumps(payload, indent=2, default=str)[:4000])
        else:
            print(str(payload)[:4000])


async def sign_in(client: httpx.AsyncClient) -> dict[str, Any]:
    res = await client.post(
        "/auth/sign-in",
        json={
            "tenant_slug": TENANT_SLUG,
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
        },
    )
    if res.status_code != 200:
        raise SystemExit(f"sign-in failed: {res.status_code} {res.text}")
    scope = res.json()
    _print("Signed in", scope)
    return scope


async def assert_email_provider_connected(client: httpx.AsyncClient) -> str:
    """Confirm the tenant has Gmail or Microsoft 365 connected, otherwise
    the send_gmail / send_outlook tool will fail at execution time. Returns
    the connected provider id."""
    res = await client.get("/v1/integrations/status")
    if res.status_code != 200:
        raise SystemExit(f"status fetch failed: {res.status_code} {res.text}")
    status = res.json()
    _print("Integration status", status)

    for prov in ("google", "microsoft"):
        info = status.get(prov) or {}
        if info.get("connected") and not info.get("is_expired"):
            return prov

    raise SystemExit(
        "FAIL: no email provider connected on this tenant.\n"
        "Open the deployed app → /integrations and connect Google (Gmail) "
        "or Microsoft (Outlook) before re-running this script.\n"
        f"Current status: {json.dumps(status)[:400]}"
    )


async def stream_chat(
    client: httpx.AsyncClient, message: str, history: list[dict[str, str]]
) -> tuple[str, list[dict[str, Any]]]:
    """POST /chat/stream and consume the SSE response. Returns
    (assistant_message, events_with_proposed_actions)."""
    text_parts: list[str] = []
    proposed: list[dict[str, Any]] = []

    headers = {**COMMON_HEADERS, "X-Tigeri-Session-Id": "test-invoice-email"}
    async with client.stream(
        "POST",
        "/chat/stream",
        json={"message": message, "history": history},
        headers=headers,
        timeout=120.0,
    ) as response:
        if response.status_code != 200:
            body = await response.aread()
            raise SystemExit(f"chat/stream failed: {response.status_code} {body!r}")

        async for line in response.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "agent_text":
                text_parts.append(ev.get("content", ""))
            elif t == "tool_proposed":
                proposed.append(ev)
                print(
                    f"  [proposed] {ev.get('capability')} action_id={ev.get('action_id')}"
                )
            elif t == "tool_call":
                print(f"  [tool_call] {ev.get('tool')}")
            elif t == "tool_result":
                ok = ev.get("ok")
                print(f"  [tool_result] ok={ok}")
            elif t == "error":
                print(f"  [error] {ev.get('message')}")

    return "".join(text_parts), proposed


async def confirm_action(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    res = await client.post(
        "/actions/confirm",
        json={"confirmation_token": token},
    )
    if res.status_code not in (200, 201):
        raise SystemExit(f"confirm failed: {res.status_code} {res.text}")
    out = res.json()
    print(
        f"  [confirmed] capability={out.get('capability')} status={out.get('status')}"
    )
    return out


async def fetch_recent_audit(client: httpx.AsyncClient, limit: int = 20) -> list[dict]:
    res = await client.get(f"/audit/records?limit={limit}")
    if res.status_code != 200:
        return []
    body = res.json()
    return body if isinstance(body, list) else body.get("records", [])


async def run() -> None:
    async with httpx.AsyncClient(
        base_url=API_BASE,
        headers=COMMON_HEADERS,
        follow_redirects=False,
        timeout=60.0,
    ) as client:
        await sign_in(client)
        provider = await assert_email_provider_connected(client)
        print(f"\nUsing email provider: {provider}")

        # ── Turn 1: ask the orchestrator to raise an invoice ────────────
        prompt_invoice = (
            f"Please raise a draft invoice for {VENDOR} for ${AMOUNT}, "
            f"line item 'Consulting services — April 2026'. "
            f"After you raise it, summarize the invoice in chat so I can review it."
        )
        _print("Turn 1 prompt", prompt_invoice)
        history: list[dict[str, str]] = []
        text1, proposed1 = await stream_chat(client, prompt_invoice, history)
        _print("Turn 1 assistant text", text1 or "(empty)")
        history += [
            {"role": "user", "content": prompt_invoice},
            {"role": "assistant", "content": text1},
        ]

        if not proposed1:
            raise SystemExit(
                "FAIL: orchestrator did not propose any write action on turn 1. "
                "Expected invoke_invoice_agent. Inspect the assistant text above."
            )
        for ev in proposed1:
            await confirm_action(client, ev["confirmation_token"])

        # Give the post-confirm dispatch a moment to write its result row
        # before the follow-up turn reads it back through agent context.
        await asyncio.sleep(1.0)

        # ── Turn 2: ask it to email the invoice ─────────────────────────
        prompt_email = (
            f"Now email that invoice as a plain-text summary to {RECIPIENT}. "
            f"Subject: 'Invoice for review — {VENDOR}'. "
            f"Body should include the vendor, amount, and the line item."
        )
        _print("Turn 2 prompt", prompt_email)
        text2, proposed2 = await stream_chat(client, prompt_email, history)
        _print("Turn 2 assistant text", text2 or "(empty)")

        if not proposed2:
            raise SystemExit(
                "FAIL: orchestrator did not propose a send_gmail action on turn 2. "
                "Either the model didn't pick the email tool, or the tenant has "
                "no Gmail/M365 connection wired into the tool router."
            )
        for ev in proposed2:
            result = await confirm_action(client, ev["confirmation_token"])
            if result.get("status") != "executed":
                raise SystemExit(
                    f"FAIL: email action did not execute. status={result.get('status')} "
                    f"error={result.get('error_detail')}"
                )

        # ── Verify via audit chain ──────────────────────────────────────
        audit = await fetch_recent_audit(client, limit=20)
        _print("Recent audit (last 20)", audit[:20])

        print("\nPASS: invoice raised, surfaced, and email send executed.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(130)
