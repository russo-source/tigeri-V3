from collections.abc import AsyncIterator

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.db import get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_id(
    x_tigeri_tenant_id: str | None = Header(default=None, alias="X-Tigeri-Tenant-Id"),
) -> str:
    if not x_tigeri_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tigeri-Tenant-Id header is required",
        )
    return x_tigeri_tenant_id
