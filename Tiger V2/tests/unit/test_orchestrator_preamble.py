"""Unit tests for the orchestrator's runtime context preamble — the block
that injects current date + tenant timezone into the LLM system message
so 'tomorrow at 10am' resolves without follow-up questions.
"""

from __future__ import annotations

from tigeri.agents.orchestrator.agent import _runtime_context_preamble as anth_pre
from tigeri.agents.orchestrator.openrouter_agent import (
    _runtime_context_preamble as or_pre,
)


def test_preamble_includes_utc_clock():
    text = anth_pre()
    assert "now (UTC):" in text
    assert "today (UTC):" in text
    assert "tomorrow (UTC):" in text


def test_preamble_with_singapore_tz_renders_local_clock():
    text = anth_pre("Asia/Singapore")
    assert "Asia/Singapore" in text
    assert "now (tenant Asia/Singapore):" in text
    # Singapore is +08:00, no DST — offset must always show as +0800
    assert "+0800" in text


def test_preamble_with_unknown_tz_falls_back_silently():
    text = anth_pre("Atlantis/Lost_City")
    # Should still render UTC lines; tenant lines are dropped
    assert "now (UTC):" in text
    assert "Atlantis" not in text


def test_openrouter_preamble_matches_anthropic_shape():
    """Both orchestrator backends should produce isomorphic preambles so
    behaviour stays identical across providers. We don't compare the now()
    strings (they differ by sub-second), just the structural contents."""
    a = anth_pre("Asia/Singapore")
    o = or_pre("Asia/Singapore")
    for marker in (
        "RUNTIME CONTEXT",
        "Asia/Singapore",
        "tomorrow (tenant):",
        "today (UTC):",
        "ISO-8601",
    ):
        assert marker in a, f"missing in agent.py preamble: {marker!r}"
        assert marker in o, f"missing in openrouter_agent.py preamble: {marker!r}"


def test_preamble_with_no_tz_still_works():
    text = anth_pre(None)
    assert "now (UTC):" in text
    assert "tenant" not in text.lower() or "tenant's" in text
