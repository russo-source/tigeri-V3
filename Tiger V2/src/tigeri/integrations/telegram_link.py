"""One-time Telegram link codes.

Replaces the audit-flagged hijack: ``/connect <tenant_id>`` allowed any
Telegram user to bind their chat to any tenant by guessing or sniffing the
ID. Now an authenticated user clicks "Link Telegram" in the web app, which
issues a short, single-use code via :func:`issue`. The Telegram bot accepts
``/connect <code>`` and consumes it via :func:`consume` — once redeemed,
the code is dead.

Codes are 8 chars (40 bits) — short enough to type on mobile, long enough
to resist online guessing for a 5-minute window.
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base

LINK_LIFETIME = timedelta(minutes=5)
_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


class InvalidLinkCodeError(Exception):
    """Code is unknown, expired, or already consumed."""


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


async def issue(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str | None = None,
) -> tuple[str, datetime]:
    """Mint a new link code for the requesting tenant. Returns (code, expires_at)."""
    code = _generate_code()
    expires_at = datetime.now(UTC) + LINK_LIFETIME
    row = TelegramLinkCode(
        code=code, tenant_id=tenant_id, user_id=user_id, expires_at=expires_at
    )
    db.add(row)
    await db.commit()
    return code, expires_at


async def consume(db: AsyncSession, *, code: str) -> str:
    """Look up + delete the code. Returns its tenant_id.

    Raises ``InvalidLinkCodeError`` for unknown / expired / already-consumed.
    """
    if not code:
        raise InvalidLinkCodeError("missing link code")
    code = code.strip().upper()

    res = await db.execute(
        select(TelegramLinkCode).where(TelegramLinkCode.code == code)
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise InvalidLinkCodeError("unknown link code")

    # One-shot consume regardless of expiry — prevents offline grinding.
    await db.execute(
        delete(TelegramLinkCode).where(TelegramLinkCode.code == code)
    )

    if row.expires_at <= datetime.now(UTC):
        raise InvalidLinkCodeError("link code expired")
    return row.tenant_id


async def cleanup_expired(db: AsyncSession) -> int:
    """Sweep job."""
    res = await db.execute(
        delete(TelegramLinkCode).where(
            TelegramLinkCode.expires_at < datetime.now(UTC)
        )
    )
    return res.rowcount or 0
