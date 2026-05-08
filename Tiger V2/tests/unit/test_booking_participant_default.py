"""Regression test for the booking_agent participant.role default.

Earlier the orchestrator (and any direct API client) had to spell out
``role: 'ATTENDEE'`` on every guest in BookingInput.participants — a
schema-validation error otherwise. The default now lets demo prompts
like 'book a meeting with russo@tigeri.ai' work without spelling out a
role per attendee.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tigeri.agents.booking.schemas import BookingInput, Participant


def test_participant_role_defaults_to_attendee():
    p = Participant(id="russo@tigeri.ai")
    assert p.role == "ATTENDEE"


def test_participant_role_explicit_value_preserved():
    p = Participant(id="russo@tigeri.ai", role="HOST")
    assert p.role == "HOST"


def test_booking_input_accepts_participants_without_role():
    """Previously this raised ValidationError on the missing role field."""
    now = datetime.now(UTC)
    bi = BookingInput(
        tenant_id="tnt_admin",
        booking_type="MEETING",
        requested_window={
            "start": now,
            "end": now + timedelta(minutes=30),
        },
        participants=[{"id": "russo@tigeri.ai"}],
        venue_id="v_default",
    )
    assert bi.participants[0].role == "ATTENDEE"
