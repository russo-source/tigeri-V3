from datetime import UTC, datetime, timedelta

import pytest

from tigeri.a2a.signing import (
    A2AEnvelope,
    ReplayCache,
    ReplayError,
    SignatureError,
    StaleTimestampError,
    sign,
    utcnow_iso,
    verify,
)


def _envelope(ts: str | None = None) -> A2AEnvelope:
    return A2AEnvelope(
        trace_id="trace_test",
        tenant_id="tnt_test",
        sender_agent_id="invoice_agent",
        recipient_agent_id="financial_reporting_agent",
        payload=b'{"invoice_id":"abc"}',
        classification="internal",
        timestamp_utc=ts or utcnow_iso(),
    )


def test_sign_then_verify_roundtrip():
    env = sign(_envelope())
    cache = ReplayCache()
    verify(env, replay_cache=cache)  # no exception


def test_verify_rejects_tampered_payload():
    env = sign(_envelope())
    env.payload = b'{"invoice_id":"different"}'
    with pytest.raises(SignatureError):
        verify(env, replay_cache=ReplayCache())


def test_verify_rejects_stale_timestamp():
    old_ts = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    env = sign(_envelope(old_ts))
    with pytest.raises(StaleTimestampError):
        verify(env, replay_cache=ReplayCache())


def test_verify_accepts_at_window_edge():
    near_ts = (datetime.now(UTC) - timedelta(seconds=20)).isoformat()
    env = sign(_envelope(near_ts))
    verify(env, replay_cache=ReplayCache())  # within 30s


def test_verify_rejects_replayed_nonce():
    env = sign(_envelope())
    cache = ReplayCache()
    verify(env, replay_cache=cache)
    with pytest.raises(ReplayError):
        verify(env, replay_cache=cache)
