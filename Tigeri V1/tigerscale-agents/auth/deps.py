"""Contain deps backend logic."""
import json
import logging
import redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from auth.security import decode_access_token
from auth.repository import get_user_by_id
from config.settings import settings


logger = logging.getLogger(__name__)
_redis = redis.from_url(settings.redis_url, decode_responses=True)
# Constant for user cache time-to-live.
USER_CACHE_TTL = 60

bearer_scheme = HTTPBearer(auto_error=False)

_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Return current user."""
    if credentials is None:
        raise _401
 
    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
 
    cache_key = f"user_cache:{user_id}"
    cached = _redis.get(cache_key)
    if cached:
        try:
            return json.loads(str(cached))
        except json.JSONDecodeError:
            _redis.delete(cache_key)
 
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
 
    cacheable = {k: v for k, v in user.items() if k != "password_hash"}
    cacheable["created_at"] = str(cacheable.get("created_at", ""))
 
    try:
        _redis.setex(cache_key, USER_CACHE_TTL, json.dumps(cacheable))
    except Exception as e:
        logger.warning("User cache write failed (non-fatal): %s", e)
 
    return cacheable


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """Return current user id."""
    if credentials is None:
        raise _401
    try:
        return decode_access_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Execute require admin."""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user