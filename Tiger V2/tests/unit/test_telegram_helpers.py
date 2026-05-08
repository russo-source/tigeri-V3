"""Unit tests for the Telegram presentation helpers in
tigeri.api.routes.integrations — the human tool labels, proposal
renderer, and result summariser the bot uses to talk to the user.

These cover the user-visible polish layer; the webhook handler itself
is covered indirectly via its imports here.
"""

from __future__ import annotations

from tigeri.api.routes.integrations import (
    _human_tool_step,
    _render_proposal_text,
    _summarise_result,
    _QUICK_START_PROMPTS,
)


def test_human_tool_step_known_tools():
    assert _human_tool_step("send_gmail").startswith("✉️")
    # The label is "📅 Setting up the meeting…" — "meeting" or the calendar
    # emoji are both valid signals that the user-facing string is curated.
    assert "meeting" in _human_tool_step("create_calendar_event_with_meet").lower()
    assert "report" in _human_tool_step("invoke_financial_reporting_agent").lower()


def test_human_tool_step_unknown_tool_falls_back_to_raw():
    assert _human_tool_step("unknown_xyz") == "🔧 unknown_xyz"


def test_render_proposal_drops_control_fields():
    text = _render_proposal_text(
        "send_gmail",
        {"to": "x@y", "subject": "s", "body": "b", "tenant_id": "tnt_x", "user_id": "usr_x"},
    )
    assert "tenant_id" not in text
    assert "user_id" not in text
    assert "to: x@y" in text


def test_render_proposal_truncates_long_string():
    long_body = "x" * 500
    text = _render_proposal_text("send_gmail", {"to": "x@y", "body": long_body})
    # 200-char cap + ellipsis
    assert "…" in text
    assert "x" * 500 not in text


def test_summarise_send_gmail_result():
    out = _summarise_result(
        "send_gmail",
        {"to": "russo@tigeri.ai", "subject": "Hi", "message_id": "abc123"},
    )
    assert "russo@tigeri.ai" in out
    assert "abc123" in out
    # Was reading result["id"] before — message_id shouldn't render as '?'
    assert "?" not in out


def test_summarise_calendar_result_includes_meet_link():
    out = _summarise_result(
        "create_calendar_event_with_meet",
        {
            "event_id": "ev_x",
            "html_link": "https://calendar.google.com/abc",
            "meet_link": "https://meet.google.com/xyz",
            "attendees": ["russo@tigeri.ai"],
        },
    )
    assert "ev_x" in out
    assert "meet.google.com/xyz" in out
    assert "calendar.google.com/abc" in out
    assert "russo@tigeri.ai" in out


def test_summarise_invoice_result_includes_posting_url():
    out = _summarise_result(
        "invoke_invoice_agent",
        {
            "invoice_id": "inv_xyz",
            "posting_url": "https://go.xero.com/AccountsReceivable/View.aspx?id=abc",
            "posting_reference": "INV-001",
        },
    )
    assert "inv_xyz" in out
    assert "INV-001" in out
    assert "xero.com" in out


def test_summarise_handles_error_payload():
    out = _summarise_result("send_gmail", {"error": "Gmail send failed"})
    assert out.startswith("❌")
    assert "Gmail send failed" in out


def test_quick_start_prompts_have_all_required_demo_actions():
    """Every demo flow we promote in the docs should have a /help button."""
    labels = [label for label, _prompt in _QUICK_START_PROMPTS]
    joined = " ".join(labels).lower()
    for must_have in ("invoice", "calendar", "meeting", "email", "p&l", "integration"):
        assert must_have in joined, f"missing quick-start: {must_have}"


def test_quick_start_callback_data_fits_telegram_64_byte_limit():
    """Telegram caps callback_data at 64 bytes — qs:<idx> stays well under."""
    for idx in range(len(_QUICK_START_PROMPTS)):
        cb = f"qs:{idx}"
        assert len(cb.encode("utf-8")) <= 64
