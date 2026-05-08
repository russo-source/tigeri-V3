import base64
import hmac
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from tigeri.core.config import get_settings
from tigeri.core.ids import new_id


@dataclass
class A2AEnvelope:
    """Python representation of TigeriA2AEnvelope (see envelope.proto).

    Fields mirror the protobuf message exactly. `hmac_sha256_sig` is populated
    by sign() and verified by verify().
    """

    trace_id: str
    tenant_id: str
    sender_agent_id: str
    recipient_agent_id: str
    payload: bytes
    classification: str
    timestamp_utc: str
    nonce: str = field(default_factory=lambda: new_id("nonce"))
    hmac_sha256_sig: str = ""

    def canonical_bytes(self) -> bytes:
        parts = [
            self.trace_id,
            self.tenant_id,
            self.sender_agent_id,
            self.recipient_agent_id,
            base64.b64encode(self.payload).decode("ascii"),
            self.classification,
            self.timestamp_utc,
            self.nonce,
        ]
        return "\n".join(parts).encode("utf-8")


class ReplayCache:
    """Bounded LRU of recently-seen (tenant_id, nonce) pairs."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._max = max_entries
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def add(self, tenant_id: str, nonce: str) -> bool:
        key = (tenant_id, nonce)
        now = time.time()
        if key in self._seen:
            return False
        self._seen[key] = now
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True


_replay_cache = ReplayCache()


class SignatureError(Exception):
    pass


class ReplayError(Exception):
    pass


class StaleTimestampError(Exception):
    pass


def sign(envelope: A2AEnvelope, secret: str | None = None) -> A2AEnvelope:
    secret_bytes = (secret or get_settings().a2a_hmac_secret).encode("utf-8")
    digest = hmac.new(secret_bytes, envelope.canonical_bytes(), sha256).digest()
    envelope.hmac_sha256_sig = base64.b64encode(digest).decode("ascii")
    return envelope


def verify(
    envelope: A2AEnvelope,
    secret: str | None = None,
    *,
    now: datetime | None = None,
    replay_cache: ReplayCache | None = None,
) -> None:
    settings = get_settings()
    secret_bytes = (secret or settings.a2a_hmac_secret).encode("utf-8")
    expected = hmac.new(secret_bytes, envelope.canonical_bytes(), sha256).digest()
    actual = base64.b64decode(envelope.hmac_sha256_sig.encode("ascii"))
    if not hmac.compare_digest(expected, actual):
        raise SignatureError("HMAC signature mismatch")

    now = now or datetime.now(UTC)
    try:
        ts = datetime.fromisoformat(envelope.timestamp_utc)
    except ValueError as e:
        raise StaleTimestampError(f"invalid timestamp: {envelope.timestamp_utc}") from e
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    window = timedelta(seconds=settings.a2a_replay_window_seconds)
    if abs(now - ts) > window:
        raise StaleTimestampError(
            f"timestamp outside ±{settings.a2a_replay_window_seconds}s window"
        )

    cache = replay_cache or _replay_cache
    if not cache.add(envelope.tenant_id, envelope.nonce):
        raise ReplayError(f"nonce reuse detected: {envelope.nonce}")


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
