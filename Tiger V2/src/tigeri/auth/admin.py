"""Role-gate dependency. Wrap any admin-only route with require_role('owner', 'admin')."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from tigeri.auth.scope import TenantScope, get_scope


def require_role(
    *allowed: str,
) -> Callable[[TenantScope], Coroutine[Any, Any, TenantScope]]:
    """FastAPI dependency factory: 403 unless scope.role is in allowed."""

    async def _dep(
        scope: Annotated[TenantScope, Depends(get_scope)],
    ) -> TenantScope:
        if scope.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role in {allowed}",
            )
        return scope

    return _dep


# Common shorthand: admin operations require owner OR admin.
require_admin = require_role("owner", "admin")
