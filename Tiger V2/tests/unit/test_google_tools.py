"""Unit tests for the orchestrator's Google tools (send_gmail,
list_calendar_events, create_calendar_event_with_meet).

We mock GoogleClient at the boundary — the tools are responsible for
shaping inputs/outputs around the client, not for re-testing the HTTP
layer. The integration test for the HTTP layer would need a real Google
account; that's out of scope for the unit suite."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tigeri.agents.orchestrator import tools


@pytest.mark.asyncio
async def test_send_gmail_returns_message_id_on_success():
    fake_client = MagicMock()
    fake_client.send_email = AsyncMock(
        return_value={"id": "msg_abc123", "threadId": "thr_xyz789"}
    )

    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.send_gmail(
            {
                "to": "alice@example.com",
                "subject": "hi",
                "body": "hello",
            },
            session=MagicMock(),
            tenant_id="tnt_admin",
        )

    assert out == {
        "ok": True,
        "message_id": "msg_abc123",
        "thread_id": "thr_xyz789",
        "to": "alice@example.com",
        "subject": "hi",
    }
    fake_client.send_email.assert_awaited_once()
    call = fake_client.send_email.await_args
    assert call.kwargs["to"] == "alice@example.com"
    assert call.kwargs["subject"] == "hi"
    assert call.kwargs["body"] == "hello"
    # Plain-text default
    assert call.kwargs["html"] is False


@pytest.mark.asyncio
async def test_send_gmail_validates_required_fields():
    out = await tools.send_gmail(
        {"to": "", "subject": "x", "body": "y"},
        session=MagicMock(),
        tenant_id="tnt_admin",
    )
    assert "error" in out
    assert "required" in out["error"]


@pytest.mark.asyncio
async def test_send_gmail_surfaces_when_google_not_connected():
    """If GoogleClient.for_tenant raises (no token / no creds), the tool
    must NOT crash the chat — it returns an error dict the LLM and chat UI
    can render."""

    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(side_effect=ValueError("no token")),
    ):
        out = await tools.send_gmail(
            {"to": "a@b.com", "subject": "x", "body": "y"},
            session=MagicMock(),
            tenant_id="tnt_admin",
        )

    assert "error" in out
    assert "Google" in out["error"]


@pytest.mark.asyncio
async def test_list_calendar_events_extracts_meet_link():
    fake_client = MagicMock()
    fake_client.list_calendar_events = AsyncMock(
        return_value=[
            {
                "id": "evt_1",
                "summary": "Standup",
                "start": {"dateTime": "2026-05-01T09:00:00Z"},
                "end": {"dateTime": "2026-05-01T09:30:00Z"},
                "attendees": [{"email": "a@x.com"}, {"email": "b@x.com"}],
                "conferenceData": {
                    "entryPoints": [
                        {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"},
                        {"entryPointType": "more", "uri": "https://meet.google.com/tel/abc"},
                    ]
                },
                "htmlLink": "https://calendar.google.com/event?eid=evt_1",
            }
        ]
    )

    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.list_calendar_events(
            {
                "time_min_iso": "2026-05-01T00:00:00Z",
                "time_max_iso": "2026-05-02T00:00:00Z",
            },
            session=MagicMock(),
            tenant_id="tnt_admin",
        )

    assert out["count"] == 1
    ev = out["events"][0]
    assert ev["summary"] == "Standup"
    assert ev["meet_link"] == "https://meet.google.com/abc-defg-hij"
    assert ev["attendees"] == ["a@x.com", "b@x.com"]


@pytest.mark.asyncio
async def test_create_calendar_event_with_meet_sends_correct_flag():
    fake_client = MagicMock()
    fake_client.create_calendar_event = AsyncMock(
        return_value={
            "id": "evt_new",
            "htmlLink": "https://calendar.google.com/event?eid=evt_new",
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/zzz-yyyy-xxx"},
                ]
            },
        }
    )

    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.create_calendar_event_with_meet(
            {
                "summary": "Demo call",
                "start_iso": "2026-05-02T14:00:00Z",
                "end_iso": "2026-05-02T15:00:00Z",
                "attendees": ["c@x.com"],
                "with_meet": True,
            },
            session=MagicMock(),
            tenant_id="tnt_admin",
        )

    assert out["ok"] is True
    assert out["event_id"] == "evt_new"
    assert out["meet_link"] == "https://meet.google.com/zzz-yyyy-xxx"
    fake_client.create_calendar_event.assert_awaited_once()
    call = fake_client.create_calendar_event.await_args
    assert call.kwargs["with_meet"] is True


@pytest.mark.asyncio
async def test_create_calendar_event_validates_required_fields():
    out = await tools.create_calendar_event_with_meet(
        {"summary": "x", "start_iso": "", "end_iso": ""},
        session=MagicMock(),
        tenant_id="tnt_admin",
    )
    assert "error" in out


def test_new_tools_are_registered_and_write_classified():
    """Belt-and-braces: TOOL_SCHEMAS, REGISTRY and WRITE_TOOLS stay aligned.
    A tool added to the schema list but missing from REGISTRY would be
    invocable by the LLM and crash at dispatch time."""

    schema_names = {s["name"] for s in tools.TOOL_SCHEMAS}
    assert "send_gmail" in schema_names
    assert "list_calendar_events" in schema_names
    assert "create_calendar_event_with_meet" in schema_names

    assert "send_gmail" in tools.REGISTRY
    assert "list_calendar_events" in tools.REGISTRY
    assert "create_calendar_event_with_meet" in tools.REGISTRY

    # Writes go through the propose-confirm gate; reads do not.
    assert "send_gmail" in tools.WRITE_TOOLS
    assert "create_calendar_event_with_meet" in tools.WRITE_TOOLS
    assert "list_calendar_events" not in tools.WRITE_TOOLS
