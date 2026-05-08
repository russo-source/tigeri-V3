"""Lock in the read-only-intent guardrail for the chat orchestrator."""

import pytest

from tigeri.agents.orchestrator.intent_guard import filter_tool_calls


WRITE_TOOLS = {
    "send_gmail",
    "create_calendar_event_with_meet",
    "invoke_invoice_agent",
}


@pytest.mark.parametrize(
    "user_message",
    [
        "find me a good restaurant in kerala",
        "Find me a good restaurant in kerala",
        "Where is Sydney Opera House",
        "show me upcoming events",
        "what's the weather in Mumbai",
        "list audit records",
        "look up Acme Pty Ltd",
        "how long is the drive from A to B",
        "is there a meeting at 10am",
        "also, find me a coffee shop nearby",  # the regression case
    ],
)
def test_drops_write_tools_when_message_is_read_only(user_message):
    """The exact bug we hit: 'find me a restaurant' was producing
    send_gmail + create_calendar_event_with_meet + find_place. Only
    find_place should survive."""

    kept, reason = filter_tool_calls(
        user_message=user_message,
        tool_names=["send_gmail", "create_calendar_event_with_meet", "find_place"],
        write_tools=WRITE_TOOLS,
    )

    assert kept == [2], f"expected only find_place to survive, kept={kept}"
    assert reason and "send_gmail" in reason and "create_calendar_event_with_meet" in reason


def test_no_drop_when_user_explicitly_asks_for_write():
    """If the user says 'send X an email' we must let send_gmail through
    even if the model also called another tool."""

    kept, reason = filter_tool_calls(
        user_message="send an email to alice@example.com saying hi",
        tool_names=["send_gmail", "find_place"],
        write_tools=WRITE_TOOLS,
    )
    assert kept == [0, 1]
    assert reason is None


def test_no_drop_when_no_read_tool_was_called():
    """If the LLM didn't call a read tool, we have nothing to fall back
    to — keep everything and let the user confirm/cancel via the
    propose-confirm gate."""

    kept, reason = filter_tool_calls(
        user_message="find me a restaurant",
        tool_names=["send_gmail"],
        write_tools=WRITE_TOOLS,
    )
    assert kept == [0]
    assert reason is None


def test_no_drop_when_only_read_tools_called():
    """The common happy path — no writes mixed in, nothing to drop."""

    kept, reason = filter_tool_calls(
        user_message="find me a restaurant",
        tool_names=["find_place"],
        write_tools=WRITE_TOOLS,
    )
    assert kept == [0]
    assert reason is None


def test_no_drop_for_ambiguous_messages():
    """If the message doesn't clearly read as a question, leave the
    decision to the model."""

    kept, reason = filter_tool_calls(
        user_message="alice@example.com",  # bare email — could be context
        tool_names=["send_gmail", "find_place"],
        write_tools=WRITE_TOOLS,
    )
    assert kept == [0, 1]
    assert reason is None


def test_handles_empty_input_safely():
    kept, reason = filter_tool_calls(
        user_message="",
        tool_names=[],
        write_tools=WRITE_TOOLS,
    )
    assert kept == []
    assert reason is None
