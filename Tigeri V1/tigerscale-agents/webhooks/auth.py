"""Contain auth backend logic."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from auth.service import (
    create_google_oauth_state,
    forgot_password,
    issue_tokens,
    login_user,
    register_user,
    reset_password,
    revoke_token,
    rotate_refresh_token,
    upsert_google_user,
    verify_google_oauth_state,
)
from config.settings import settings
from security.rate_limiter import check_rate_limit
from auth.deps import get_current_user
from fastapi import Depends

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Constant for cookie maximum age.
COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60


class RegisterRequest(BaseModel):
    """Represent the RegisterRequest component and its related behavior."""
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """Represent the LoginRequest component and its related behavior."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Represent the ForgotPasswordRequest component and its related behavior."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Represent the ResetPasswordRequest component and its related behavior."""
    token: str
    new_password: str = Field(min_length=8, max_length=128)


def _set_refresh_cookie(response: Response, token: str):
    
    """Set refresh cookie."""
    is_cross_site = settings.frontend_url != settings.backend_url

    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none" if is_cross_site else "lax",       
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


def _check_auth_rate_limit(request: Request):
    """Check auth rate limit."""
    client_ip = request.client.host if request.client else "unknown"
    allowed, _ = check_rate_limit(
        client_id=f"ip:{client_ip}",
        endpoint="/api/v1/auth",
        limit=20,
        window=60,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests")


@router.post("/register")
def register(payload: RegisterRequest, request: Request, response: Response):
    """Execute register."""
    _check_auth_rate_limit(request)
    try:
        user = register_user(payload.email, payload.name, payload.password)
        access_token, refresh_token = issue_tokens(user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    """Execute login."""
    _check_auth_rate_limit(request)
    try:
        user = login_user(payload.email, payload.password)
        access_token, refresh_token = issue_tokens(user["id"])
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    _set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh")
def refresh(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
):
    """Execute refresh."""
    token = refresh_token or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing refresh token")

    try:
        access_token, new_refresh = rotate_refresh_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    user: dict = Depends(get_current_user),
):
    """Execute logout."""
    from auth.service import revoke_all_tokens
    revoke_all_tokens(user["id"])
    response.delete_cookie("refresh_token", samesite="none", secure=True)
    return {"message": "Logged out successfully"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Execute me."""
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "provider": user["provider"],
        "avatar_url": user["avatar_url"],
        "client_id": user["client_id"],
        "is_admin": user["is_admin"],
        "created_at": str(user["created_at"]),
    }


@router.post("/forgot-password")
def forgot_password_endpoint(payload: ForgotPasswordRequest, request: Request):
    """Execute forgot password endpoint."""
    _check_auth_rate_limit(request)
    reset_link = forgot_password(payload.email)

    if settings.env != "production" and reset_link:
        return {"message": f"Reset link: {reset_link}"}

    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
def reset_password_endpoint(payload: ResetPasswordRequest):
    """Execute reset password endpoint."""
    try:
        reset_password(payload.token, payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Password reset successful"}


@router.get("/google/login")
def google_login():
    """Execute google login."""
    state = create_google_oauth_state()
    from integrations.google_oauth import build_google_auth_url
    return RedirectResponse(url=build_google_auth_url(state), status_code=307)


@router.get("/google/callback")
async def google_callback(code: str, state: str, response: Response):
    """Execute google callback."""
    try:
        verify_google_oauth_state(state)
        from integrations.google_oauth import exchange_google_code, fetch_google_profile
        tokens = await exchange_google_code(code)
        profile = await fetch_google_profile(tokens["access_token"])
        user = upsert_google_user(profile)
        access_token, refresh_token = issue_tokens(user["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Google authentication failed")

    redirect = RedirectResponse(
        url=f"{settings.frontend_url}/auth/callback?access_token={access_token}",
        status_code=302,
    )
    _set_refresh_cookie(redirect, refresh_token)
    redirect.set_cookie(
        key="access_token_once",
        value=access_token,
        httponly=False,
        secure=True,
        samesite="none",
        max_age=30,
    )
    return redirect