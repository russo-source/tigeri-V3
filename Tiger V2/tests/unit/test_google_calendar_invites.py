"""Regression test for the Google Calendar invite-email bug.

Google's events.insert defaults sendUpdates=none, which means attendees
get added to the event but never receive the invitation email. We patched
GoogleClient.create_calendar_event to force sendUpdates=all whenever
there's at least one attendee. This test pins that behaviour so the same
silent regression doesn't return.
"""

from __future__ import annotations

import pytest

from tigeri.integrations.google import CalendarEvent, GoogleClient


@pytest.mark.asyncio
async def test_create_calendar_event_passes_sendUpdates_all_when_attendees():
    """With at least one attendee, the request must include
    sendUpdates=all so Google emails the invitation."""

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"id": "ev_x", "htmlLink": "https://cal/x"}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, _url, *, headers=None, json=None, params=None):
            captured["params"] = params
            captured["payload"] = json
            return _FakeResp()

    client = GoogleClient(access_token="t")

    import httpx as _httpx  # noqa: WPS433
    orig = _httpx.AsyncClient
    _httpx.AsyncClient = lambda *_a, **_kw: _FakeClient()  # type: ignore[assignment]
    try:
        await client.create_calendar_event(
            CalendarEvent(
                summary="Demo sync",
                start_iso="2026-05-01T02:00:00+00:00",
                end_iso="2026-05-01T02:30:00+00:00",
                attendees=["russo@tigeri.ai"],
            ),
            with_meet=True,
        )
    finally:
        _httpx.AsyncClient = orig  # type: ignore[assignment]

    assert captured["params"].get("sendUpdates") == "all", (
        "sendUpdates must be 'all' when attendees are present — otherwise "
        "Google silently skips the invitation email"
    )
    # And conferenceDataVersion stays correct so the Meet link still mints
    assert captured["params"].get("conferenceDataVersion") == "1"


@pytest.mark.asyncio
async def test_create_calendar_event_skips_sendUpdates_when_no_attendees():
    """Attendee-less events (a self-only block-out) shouldn't trigger any
    notification — Google's default 'none' is correct in that case."""

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"id": "ev_y"}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, _url, *, headers=None, json=None, params=None):
            captured["params"] = params
            return _FakeResp()

    client = GoogleClient(access_token="t")

    import httpx as _httpx
    orig = _httpx.AsyncClient
    _httpx.AsyncClient = lambda *_a, **_kw: _FakeClient()  # type: ignore[assignment]
    try:
        await client.create_calendar_event(
            CalendarEvent(
                summary="Focus block",
                start_iso="2026-05-01T02:00:00+00:00",
                end_iso="2026-05-01T03:00:00+00:00",
                attendees=[],
            ),
            with_meet=False,
        )
    finally:
        _httpx.AsyncClient = orig  # type: ignore[assignment]

    assert "sendUpdates" not in (captured["params"] or {})
