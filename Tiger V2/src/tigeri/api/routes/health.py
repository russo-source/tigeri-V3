from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.api.deps import get_session

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Cheap liveness probe — does not touch the DB. Use for ELB health
    checks and `Restart=on-failure` style supervisors."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Readiness probe — verifies the API can talk to Postgres and that the
    Fernet encryption key round-trips. A 503 here means "do not route traffic
    to me yet" (vs `/healthz` which only says the process is up).

    Decrypt round-trip catches the silent failure mode where the saved key
    no longer matches the OAuth tokens in the DB — without this check, every
    Xero/QB call would 401 in the user's chat with no operator alert."""

    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db: {type(e).__name__}") from e

    try:
        from tigeri.integrations.encryption import decrypt, encrypt

        round_trip = decrypt(encrypt("readyz"))
        if round_trip != "readyz":
            raise RuntimeError("crypto round-trip mismatch")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"crypto: {type(e).__name__}"
        ) from e

    return {"status": "ready"}


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Anyone hitting the API root (e.g. via the EC2 hostname on port 8000)
    is bounced to the frontend so they don't get a bare FastAPI 404."""
    return RedirectResponse(url="http://ec2-100-48-88-95.compute-1.amazonaws.com/")
