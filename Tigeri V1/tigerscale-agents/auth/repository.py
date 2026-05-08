"""Contain repository backend logic."""
from datetime import datetime, timezone
from typing import Optional
from config.db_pool import get_conn
from auth.security import new_uuid


def get_user_by_email(email: str) -> Optional[dict]:
    """Return user by email."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, password_hash, provider,
                   google_id, avatar_url, client_id, is_admin,
                   created_at
            FROM users WHERE email = %s
        """, (email,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return _row_to_user(row)


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Return user by id."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, password_hash, provider,
                   google_id, avatar_url, client_id, is_admin,
                   created_at
            FROM users WHERE id = %s
        """, (user_id,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return _row_to_user(row)


def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Return user by google id."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, password_hash, provider,
                   google_id, avatar_url, client_id, is_admin,
                   created_at
            FROM users WHERE google_id = %s
        """, (google_id,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return _row_to_user(row)


def create_user(
    email: str,
    name: str,
    password_hash: Optional[str] = None,
    provider: str = "local",
    google_id: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> dict:
    """Create user."""
    user_id = new_uuid()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users
            (id, email, name, password_hash, provider, google_id, avatar_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, name, password_hash, provider,
                      google_id, avatar_url, client_id, is_admin, created_at
        """, (user_id, email, name, password_hash, provider, google_id, avatar_url))
        row = cur.fetchone()
        cur.close()
    return _row_to_user(row)


def update_user_google(
    user_id: str,
    google_id: str,
    name: str,
    avatar_url: Optional[str],
) -> dict:
    """Update user google."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET google_id = %s, name = %s, avatar_url = %s,
                provider = 'google', updated_at = NOW()
            WHERE id = %s
            RETURNING id, email, name, password_hash, provider,
                      google_id, avatar_url, client_id, is_admin, created_at
        """, (google_id, name, avatar_url, user_id))
        row = cur.fetchone()
        cur.close()
    return _row_to_user(row)


def set_user_client_id(user_id: str, client_id: str):
    """Set user client id."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET client_id = %s, updated_at = NOW()
            WHERE id = %s
        """, (client_id, user_id))
        cur.close()


def store_refresh_token(
    user_id: str,
    token: str,
    expires_at: datetime,
):
    """Execute store refresh token."""
    token_id = new_uuid()
    # cleanup expired tokens first
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM refresh_tokens
            WHERE user_id = %s AND expires_at < NOW()
        """, (user_id,))
        cur.execute("""
            INSERT INTO refresh_tokens (id, user_id, token, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (token_id, user_id, token, expires_at))
        cur.close()


def get_refresh_token(token: str) -> Optional[dict]:
    """Return refresh token."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, token, expires_at
            FROM refresh_tokens WHERE token = %s
        """, (token,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "token": row[2],
        "expires_at": row[3],
    }


def delete_refresh_token(token: str):
    """Delete refresh token."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM refresh_tokens WHERE token = %s",
            (token,)
        )
        cur.close()


def store_password_reset_token(
    user_id: str,
    token: str,
    expires_at: datetime,
):
    """Execute store password reset token."""
    token_id = new_uuid()
    with get_conn() as conn:
        cur = conn.cursor()
        # revoke existing unused tokens
        cur.execute("""
            DELETE FROM password_reset_tokens
            WHERE user_id = %s AND used_at IS NULL
        """, (user_id,))
        cur.execute("""
            INSERT INTO password_reset_tokens (id, user_id, token, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (token_id, user_id, token, expires_at))
        cur.close()


def get_password_reset_token(token: str) -> Optional[dict]:
    """Return password reset token."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, token, expires_at, used_at
            FROM password_reset_tokens WHERE token = %s
        """, (token,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "token": row[2],
        "expires_at": row[3],
        "used_at": row[4],
    }


def mark_reset_token_used(token: str):
    """Execute mark reset token used."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE password_reset_tokens
            SET used_at = NOW() WHERE token = %s
        """, (token,))
        cur.close()


def store_oauth_state(state: str, provider: str, expires_at: datetime):
    """Execute store oauth state."""
    state_id = new_uuid()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO oauth_states (id, provider, state, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (state_id, provider, state, expires_at))
        cur.close()


def get_and_delete_oauth_state(state: str) -> Optional[dict]:
    """Return and delete oauth state."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM oauth_states WHERE state = %s
            RETURNING provider, expires_at
        """, (state,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    return {"provider": row[0], "expires_at": row[1]}


def _row_to_user(row) -> dict:
    """Execute row to user."""
    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "password_hash": row[3],
        "provider": row[4],
        "google_id": row[5],
        "avatar_url": row[6],
        "client_id": row[7],
        "is_admin": row[8],
        "created_at": row[9],
    }