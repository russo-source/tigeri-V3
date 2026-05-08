"""Contain admin init backend logic."""
from __future__ import annotations

import json
import logging
import secrets

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from auth.deps import require_admin
from auth.service import register_user
from config.db_pool import get_conn
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-init"])
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

# Constant for admin limit.
ADMIN_LIMIT = 2
# Constant for pending key.
PENDING_KEY = "admin:pending_approvals"


def _get_admin_count() -> int:
    """Return admin count."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
        count = cur.fetchone()[0]
        cur.close()
    return count


def _hash_password(password: str) -> str:
    """Execute hash password."""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


class AdminInitRequest(BaseModel):
    """Represent the AdminInitRequest component and its related behavior."""
    secret: str
    email: EmailStr
    name: str
    password: str


class AdminApproveRequest(BaseModel):
    """Represent the AdminApproveRequest component and its related behavior."""
    email: EmailStr
    secret:str


class AdminRequestAccess(BaseModel):
    """Represent the AdminRequestAccess component and its related behavior."""
    email: EmailStr
    name: str
    password: str


@router.post("/init")
def init_admin(payload: AdminInitRequest) -> dict:
    """Initialize admin."""
    if not secrets.compare_digest(payload.secret, settings.admin_init_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    if _get_admin_count() >= ADMIN_LIMIT:
        raise HTTPException(status_code=400, detail=f"Admin limit of {ADMIN_LIMIT} already reached")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (payload.email,))
        existing = cur.fetchone()
        cur.close()

    if existing:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_admin = TRUE WHERE email = %s RETURNING id",
                        (payload.email,))
            row = cur.fetchone()
            cur.close()
        return {"status": "promoted", "user_id": str(row[0])}
    

    try:
        user = register_user(payload.email, payload.name, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user["id"],))
        cur.close()

    return {"status": "created", "user_id": str(user["id"])}


@router.post("/request-access")
def request_admin_access(payload: AdminRequestAccess, request: Request) -> dict:
    """Execute request admin access."""
    from security.rate_limiter import check_rate_limit
    client_ip = request.client.host if request.client else "unknown"
    allowed, _ = check_rate_limit(f"ip:{client_ip}", "/api/v1/admin/request-access",
                                  limit=3, window=3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    if _get_admin_count() >= ADMIN_LIMIT:
        raise HTTPException(status_code=400,
                            detail="Admin slots are full. Contact the existing administrators.")

    if _redis.hexists(PENDING_KEY, payload.email):
        raise HTTPException(status_code=400,
                            detail="A request for this email is already pending.")

    pending = {
        "email": payload.email,
        "name": payload.name,
        "password_hashed": _hash_password(payload.password),
    }
    _redis.hset(PENDING_KEY, payload.email, json.dumps(pending))
    _redis.expire(PENDING_KEY, 48 * 3600)
    return {"status": "pending", "message": "Request submitted. An admin will review it."}


@router.get("/pending-requests")
def get_pending_requests(admin: dict = Depends(require_admin)) -> dict:
    """Return pending requests."""
    raw = _redis.hgetall(PENDING_KEY)
    return {
        "pending": [
            {"email": k, "name": json.loads(v).get("name", "")}
            for k, v in raw.items()  # type: ignore
        ]
    }


@router.post("/approve")
def approve_admin(payload: AdminApproveRequest, admin: dict = Depends(require_admin)) -> dict:
    """Execute approve admin."""
    if not secrets.compare_digest(payload.secret, settings.admin_init_secret):
        raise HTTPException(status_code=403, detail="Invalid secret key.")

    if _get_admin_count() >= ADMIN_LIMIT:
        raise HTTPException(status_code=400, detail=f"Admin limit of {ADMIN_LIMIT} already reached.")

    raw = _redis.hget(PENDING_KEY, payload.email)
    if not raw:
        raise HTTPException(status_code=404, detail="No pending request for this email")

    pending = json.loads(raw)  # type: ignore

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (payload.email,))
        existing = cur.fetchone()
        cur.close()

    if existing:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_admin = TRUE WHERE email = %s RETURNING id",
                        (payload.email,))
            row = cur.fetchone()
            cur.close()
        user_id = str(row[0])
    else:
        try:
            user = register_user(payload.email, pending["name"],
                                 pending.get("password_hashed", ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user["id"],))
            cur.close()
        user_id = str(user["id"])

    _redis.hdel(PENDING_KEY, payload.email)
    return {"status": "approved", "user_id": user_id}

@router.post("/reject")
def reject_admin(payload: AdminApproveRequest, admin: dict = Depends(require_admin)) -> dict:
    """Execute reject admin."""
    deleted = _redis.hdel(PENDING_KEY, payload.email)
    if not deleted:
        raise HTTPException(status_code=404, detail="No pending request for this email")
    return {"status": "rejected"}