"""Session creation, lookup, and revocation.

Tokens: 256 bits of entropy from secrets.token_urlsafe(32). The raw token is
returned once (set as HTTP-only cookie); only its SHA-256 hash is stored.
Sliding window: each lookup extends expires_at by SESSION_LIFETIME.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.auth.models import Session
from tigeri.core.ids import new_id

SESSION_LIFETIME = timedelta(days=30)
TOUCH_DEBOUNCE = timedelta(minutes=5)
COOKIE_NAME = "tigeri_session"


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[Session, str]:
    raw_token = generate_token()
    now = datetime.now(UTC)
    session = Session(
        id=new_id("ses"),
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=hash_token(raw_token),
        user_agent=user_agent,
        ip_address=ip_address,
        last_active_at=now,
        expires_at=now + SESSION_LIFETIME,
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def get_active_session(db: AsyncSession, raw_token: str) -> Session | None:
    if not raw_token:
        return None
    th = hash_token(raw_token)
    res = await db.execute(select(Session).where(Session.token_hash == th))
    session = res.scalar_one_or_none()
    if not session:
        return None
    # SQLite stores DateTime(timezone=True) without the tzinfo, so the value
    # comes back naive. Normalise both sides to UTC before comparing so the
    # check works on both Postgres (native tz) and sqlite (test harness).
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    return session


async def touch_session(db: AsyncSession, session: Session) -> None:
    """Extend the sliding window. Debounced — only writes if the previous
    touch was more than TOUCH_DEBOUNCE ago, to avoid a write per request.
    """
    now = datetime.now(UTC)
    last = session.last_active_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if (now - last) < TOUCH_DEBOUNCE:
        return
    await db.execute(
        update(Session)
        .where(Session.id == session.id)
        .values(last_active_at=now, expires_at=now + SESSION_LIFETIME)
    )
    session.last_active_at = now
    session.expires_at = now + SESSION_LIFETIME


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    if not raw_token:
        return
    await db.execute(delete(Session).where(Session.token_hash == hash_token(raw_token)))


async def revoke_all_for_user(db: AsyncSession, user_id: str) -> None:
    """Used on offboarding / suspension to log the user out everywhere."""
    await db.execute(delete(Session).where(Session.user_id == user_id))


async def cleanup_expired(db: AsyncSession, *, grace: timedelta = timedelta(days=7)) -> int:
    """Delete sessions whose expires_at + grace is in the past.
    Run from a scheduled job (cron / k8s CronJob / etc.).
    Returns the number of rows deleted.
    """
    cutoff = datetime.now(UTC) - grace
    res = await db.execute(delete(Session).where(Session.expires_at < cutoff))
    return res.rowcount or 0
