"""Contain security backend logic."""
import uuid
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
import bcrypt
import jwt
from jwt.types import Options
from typing import cast
from config.settings import settings
import secrets

# Constant for algorithm.
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Execute hash password."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Execute verify password."""
    return bcrypt.checkpw(
        plain.encode("utf-8"),
        hashed.encode("utf-8")
    )


def create_access_token(user_id: str) -> str:
    """Create access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(
            minutes=settings.access_token_expire_minutes
        )).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def create_refresh_token() -> tuple[str, datetime]:
    """Create refresh token."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    return token_urlsafe(48), expires_at


def create_password_reset_token() -> tuple[str, datetime]:
    """Create password reset token."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.forgot_password_token_expire_minutes
    )
    return token_urlsafe(48), expires_at


def decode_access_token(token: str) -> str:
    """Execute decode access token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[ALGORITHM],
            options=cast(Options, {
                "require": ["exp", "iat", "sub"],
                "leeway": 10,
            }),
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

    if payload.get("type") != "access":
        raise ValueError("Invalid token type")

    iat = payload.get("iat", 0)
    if iat > int(datetime.now(timezone.utc).timestamp()) + 30:
        raise ValueError("Token issued in the future")

    subject = payload.get("sub")
    if not subject:
        raise ValueError("Invalid token subject")

    return str(subject)


def new_uuid() -> str:
    """Execute new uuid."""
    return str(uuid.uuid4())