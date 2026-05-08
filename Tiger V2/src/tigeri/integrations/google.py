"""Google OAuth 2.0 + Calendar API client.

Scopes used:
- ``https://www.googleapis.com/auth/calendar`` — Booking Agent conflict checks
- ``https://www.googleapis.com/auth/gmail.send`` — Admin Agent outbound email
- ``openid email profile`` — basic identity

Endpoints:
- Authorize:  https://accounts.google.com/o/oauth2/v2/auth
- Token:      https://oauth2.googleapis.com/token
- Calendar:   https://www.googleapis.com/calendar/v3/calendars/primary/events
- Gmail send: https://gmail.googleapis.com/gmail/v1/users/me/messages/send
"""

from __future__ import annotations

import base64
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.config import get_settings
from tigeri.integrations import token_manager


AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_BASE = "https://www.googleapis.com/calendar/v3"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

DEFAULT_SCOPES = " ".join(
    [
        "openid",
        "email",
        "profile",
        # Calendar — read & write events
        "https://www.googleapis.com/auth/calendar",
        # Gmail — read inbox + send
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        # Drive — file-level scope (only files this app creates/opens)
        "https://www.googleapis.com/auth/drive.file",
        # Sheets — read & write
        "https://www.googleapis.com/auth/spreadsheets",
    ]
)


def _redirect_uri() -> str:
    base = get_settings().public_api_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/callback/google"


def authorize_url(
    tenant_id: str,
    *,
    state: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> tuple[str, str]:
    """Build the OAuth authorize URL. BYOA-aware (see :mod:`tigeri.integrations.tenant_creds`)."""
    settings = get_settings()
    if state is None:
        state = f"{tenant_id}:{secrets.token_urlsafe(24)}"
    effective_scope = " ".join(scopes) if scopes else DEFAULT_SCOPES
    params = {
        "response_type": "code",
        "client_id": client_id or settings.google_client_id,
        "redirect_uri": redirect_uri or _redirect_uri(),
        "scope": effective_scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


async def exchange_code(
    session: AsyncSession,
    *,
    tigeri_tenant_id: str,
    code: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    cid = client_id or settings.google_client_id
    csec = client_secret or settings.google_client_secret
    redir = redirect_uri or _redirect_uri()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": cid,
                "client_secret": csec,
                "redirect_uri": redir,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        token = resp.json()

        # Fetch the user's email + name to display in the UI
        userinfo = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        userinfo.raise_for_status()
        u = userinfo.json()

    meta = {
        "google_email": u.get("email", ""),
        "google_name": u.get("name", ""),
        "scope": token.get("scope", DEFAULT_SCOPES),
    }
    await token_manager.save(
        session,
        tenant_id=tigeri_tenant_id,
        provider="google",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        expires_in_seconds=int(token.get("expires_in", 3600)),
        meta=meta,
    )
    return meta


async def _refresh_google(
    refresh_token: str,
    _meta: dict,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id or settings.google_client_id,
                "client_secret": client_secret or settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()


# ---- Calendar client ----------------------------------------------------


@dataclass
class CalendarEvent:
    summary: str
    start_iso: str
    end_iso: str
    attendees: list[str]


class GoogleClient:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    @classmethod
    async def for_tenant(cls, session: AsyncSession, tigeri_tenant_id: str) -> "GoogleClient":
        from tigeri.integrations import tenant_creds

        creds = await tenant_creds.resolve(
            session, tenant_id=tigeri_tenant_id, provider="google"
        )

        async def _refresh(refresh_token: str, meta: dict) -> dict[str, Any]:
            return await _refresh_google(
                refresh_token,
                meta,
                client_id=creds.client_id,
                client_secret=creds.client_secret,
            )

        token = await token_manager.get_access_token(
            session, tigeri_tenant_id, "google", refresh_fn=_refresh
        )
        return cls(access_token=token.access_token)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def create_calendar_event(
        self,
        ev: CalendarEvent,
        *,
        with_meet: bool = False,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create a primary-calendar event. When ``with_meet=True`` we attach
        a ``conferenceData.createRequest`` and pass ``conferenceDataVersion=1``
        on the query string — that's the magic combination that makes Google
        actually mint a Meet link for the event."""

        payload: dict[str, Any] = {
            "summary": ev.summary,
            "start": {"dateTime": ev.start_iso},
            "end": {"dateTime": ev.end_iso},
            "attendees": [{"email": a} for a in ev.attendees],
        }
        if description:
            payload["description"] = description
        if location:
            payload["location"] = location
        params: dict[str, Any] = {}
        # Google Calendar defaults sendUpdates=none — meaning attendees get
        # added to the event silently and NEVER receive the invite email.
        # Force ``all`` whenever there's at least one attendee so the host's
        # "Schedule a meeting with X" prompt actually reaches X.
        if ev.attendees:
            params["sendUpdates"] = "all"
        if with_meet:
            payload["conferenceData"] = {
                "createRequest": {
                    "requestId": secrets.token_hex(8),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            params["conferenceDataVersion"] = "1"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{CAL_BASE}/calendars/primary/events",
                headers=self._headers,
                json=payload,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_calendar_events(
        self,
        *,
        time_min_iso: str,
        time_max_iso: str,
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        """Return upcoming events in the window, sorted by start time. Used
        both by the agent (free/busy probes) and the chat tool the user asks
        questions like 'what's on my calendar tomorrow'."""

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CAL_BASE}/calendars/primary/events",
                headers=self._headers,
                params={
                    "timeMin": time_min_iso,
                    "timeMax": time_max_iso,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": str(max(1, min(max_results, 100))),
                },
            )
            resp.raise_for_status()
            return resp.json().get("items", []) or []

    async def has_conflict(self, start_iso: str, end_iso: str) -> bool:
        items = await self.list_calendar_events(
            time_min_iso=start_iso, time_max_iso=end_iso, max_results=5
        )
        return len(items) > 0

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        html: bool = False,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """RFC-822 message → base64url → Gmail send. Plain-text by default;
        set ``html=True`` to send the body as text/html (basic markup, no
        multipart/alternative — keep it simple)."""

        headers_lines: list[str] = [f"To: {to}"]
        if cc:
            headers_lines.append(f"Cc: {', '.join(cc)}")
        if bcc:
            headers_lines.append(f"Bcc: {', '.join(bcc)}")
        if reply_to:
            headers_lines.append(f"Reply-To: {reply_to}")
        headers_lines.append(f"Subject: {subject}")
        headers_lines.append(
            "Content-Type: text/html; charset=utf-8" if html else "Content-Type: text/plain; charset=utf-8"
        )
        raw = "\r\n".join(headers_lines) + "\r\n\r\n" + body
        encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GMAIL_BASE}/users/me/messages/send",
                headers=self._headers,
                json={"raw": encoded},
            )
            resp.raise_for_status()
            return resp.json()

    # ---- Sheets v4 ------------------------------------------------------

    async def read_sheet(
        self, spreadsheet_id: str, range_a1: str
    ) -> list[list[Any]]:
        """Read an A1 range from a sheet. Returns a 2-D list (rows of cells).
        Empty rows / cells come back as empty strings, not None."""

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_a1}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json().get("values", []) or []

    async def append_sheet_row(
        self, spreadsheet_id: str, range_a1: str, values: list[list[Any]]
    ) -> dict[str, Any]:
        """Append one or more rows to the bottom of a tab. ``range_a1``
        only needs the tab name (e.g. ``Sheet1``) — the API picks the next
        empty row. Returns the inserted range + count."""

        params = {
            "valueInputOption": "USER_ENTERED",  # honour formulas, dates, etc.
            "insertDataOption": "INSERT_ROWS",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_a1}:append",
                headers=self._headers,
                params=params,
                json={"values": values},
            )
            resp.raise_for_status()
            body = resp.json()
        updates = body.get("updates") or {}
        return {
            "spreadsheet_id": spreadsheet_id,
            "updated_range": updates.get("updatedRange", ""),
            "updated_rows": updates.get("updatedRows", 0),
            "updated_cells": updates.get("updatedCells", 0),
        }

    # ---- Drive v3 -------------------------------------------------------

    async def list_drive_files(
        self, *, query: str = "", page_size: int = 25
    ) -> list[dict[str, Any]]:
        """List recent files in the user's Drive. ``query`` is a Drive
        search expression (e.g. ``mimeType='application/vnd.google-apps.spreadsheet'``).
        We restrict to files the user owns / has access to via their OAuth
        token; ``drive.file`` scope already limits us to files this app
        created or that the user explicitly opened with us, so this won't
        leak the user's whole Drive."""

        params = {
            "pageSize": str(max(1, min(page_size, 100))),
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            "orderBy": "modifiedTime desc",
        }
        if query:
            params["q"] = query
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{DRIVE_BASE}/files", headers=self._headers, params=params
            )
            resp.raise_for_status()
            return resp.json().get("files", []) or []

    async def create_drive_doc(
        self,
        title: str,
        *,
        body: str = "",
        mime_type: str = "text/html",
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Google Doc by uploading content with the right
        target MIME type. Drive's ``upload`` endpoint converts text/html
        and text/plain into a native Google Doc when the metadata's
        ``mimeType`` is ``application/vnd.google-apps.document``.

        Returns the new file id, the human-friendly webViewLink, and the
        MIME type Drive ended up with."""

        # Multipart upload: metadata JSON + body, separated by a boundary.
        boundary = f"tigeri_drive_{secrets.token_hex(8)}"
        metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if folder_id:
            metadata["parents"] = [folder_id]

        import json as _json

        parts = [
            f"--{boundary}",
            "Content-Type: application/json; charset=utf-8",
            "",
            _json.dumps(metadata),
            f"--{boundary}",
            f"Content-Type: {mime_type}; charset=utf-8",
            "",
            body,
            f"--{boundary}--",
            "",
        ]
        payload = "\r\n".join(parts).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{DRIVE_UPLOAD_BASE}/files",
                headers=headers,
                params={
                    "uploadType": "multipart",
                    "fields": "id,name,mimeType,webViewLink",
                },
                content=payload,
            )
            resp.raise_for_status()
            return resp.json()
