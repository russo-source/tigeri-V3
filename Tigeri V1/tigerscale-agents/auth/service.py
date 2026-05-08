"""Contain service backend logic."""
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Optional

from auth.repository import (
    create_user,
    delete_refresh_token,
    get_and_delete_oauth_state,
    get_password_reset_token,
    get_refresh_token,
    get_user_by_email,
    get_user_by_google_id,
    get_user_by_id,
    store_oauth_state,
    store_password_reset_token,
    store_refresh_token,
    update_user_google,
)
from auth.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from config.db_pool import get_conn
from config.settings import settings
from security.audit import log_action


def register_user(email: str, name: str, password: str) -> dict:
    """Execute register user."""
    existing = get_user_by_email(email.lower())
    if existing:
        raise ValueError("Email already registered")

    user = create_user(
        email=email.lower(),
        name=name.strip(),
        password_hash=hash_password(password),
        provider="local",
    )

    log_action(
        client_id=user["id"],
        agent_name="auth",
        intent="register",
        input_text=email,
        output={"user_id": user["id"]},
        status="success",
    )

    return user


def login_user(email: str, password: str) -> dict:
    """Execute login user."""
    user = get_user_by_email(email.lower())
    if not user or not user.get("password_hash"):
        raise ValueError("Invalid email or password")

    if not verify_password(password, user["password_hash"]):
        raise ValueError("Invalid email or password")

    log_action(
        client_id=user["id"],
        agent_name="auth",
        intent="login",
        input_text=email,
        output={"user_id": user["id"]},
        status="success",
    )

    return user


def issue_tokens(user_id: str) -> tuple[str, str]:
    """Execute issue tokens."""
    access_token = create_access_token(user_id)
    refresh_token, expires_at = create_refresh_token()
    store_refresh_token(user_id, refresh_token, expires_at)
    return access_token, refresh_token


def rotate_refresh_token(token: str) -> tuple[str, str]:
    """Execute rotate refresh token."""
    record = get_refresh_token(token)
    if not record:
        raise ValueError("Invalid refresh token")

    if record["expires_at"] < datetime.now(timezone.utc):
        delete_refresh_token(token)
        raise ValueError("Refresh token expired")

    user = get_user_by_id(record["user_id"])
    if not user:
        raise ValueError("User not found")

    delete_refresh_token(token)
    return issue_tokens(user["id"])


def revoke_token(token: str):
    """Execute revoke token."""
    delete_refresh_token(token)


def revoke_all_tokens(user_id: str):
    """Execute revoke all tokens."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM refresh_tokens WHERE user_id = %s", (user_id,))
        cur.close()
        
def get_user_from_token(token: str) -> dict:
    """Return user from token."""
    from auth.security import decode_access_token
    user_id = decode_access_token(token)
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")
    return user


def forgot_password(email: str) -> Optional[str]:
    """Execute forgot password."""
    user = get_user_by_email(email.lower())
    if not user:
        return None

    token, expires_at = create_password_reset_token()
    store_password_reset_token(user["id"], token, expires_at)

    reset_link = f"{settings.frontend_url}/reset-password?token={token}"
    return reset_link


def reset_password(token: str, new_password: str):
    """Execute reset password."""
    record = get_password_reset_token(token)
    if not record:
        raise ValueError("Invalid reset token")

    if record["used_at"] is not None:
        raise ValueError("Reset token already used")

    if record["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("Reset token expired")

    user = get_user_by_id(record["user_id"])
    if not user:
        raise ValueError("User not found")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET password_hash = %s, updated_at = NOW()
            WHERE id = %s
        """, (hash_password(new_password), user["id"]))
        cur.execute(
            "DELETE FROM refresh_tokens WHERE user_id = %s",
            (user["id"],)
        )
        cur.execute("""
            UPDATE password_reset_tokens
            SET used_at = NOW() WHERE token = %s
        """, (token,))
        cur.close()


def create_google_oauth_state() -> str:
    """Create google oauth state."""
    state = token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    store_oauth_state(state, "google", expires_at)
    return state


def verify_google_oauth_state(state: str):
    """Execute verify google oauth state."""
    record = get_and_delete_oauth_state(state)
    if not record:
        raise ValueError("Invalid OAuth state")
    if record["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("OAuth state expired")


def upsert_google_user(profile: dict) -> dict:
    """Execute upsert google user."""
    google_id = str(profile.get("sub", "")).strip()
    if not google_id:
        raise ValueError("Missing Google profile id")

    email = str(profile.get("email", "")).strip().lower()
    name = str(profile.get("name", "")).strip() or "Google User"
    avatar_url = profile.get("picture")

    user = get_user_by_google_id(google_id)
    if user:
        return update_user_google(user["id"], google_id, name, avatar_url)

    existing = get_user_by_email(email) if email else None
    if existing:
        return update_user_google(existing["id"], google_id, name, avatar_url)

    return create_user(
        email=email or f"{google_id}@google-oauth.local",
        name=name,
        provider="google",
        google_id=google_id,
        avatar_url=avatar_url,
    )