"""Phase 1 auth: tenant-scoped users, hashed-token sessions, cookie+header scope resolver.

Coexists with the legacy header-only auth in tigeri.api.deps so existing
clients (the current frontend, integration callbacks) keep working unchanged.
"""

from tigeri.auth.models import Session, User
from tigeri.auth.scope import TenantScope, get_scope, get_scope_optional

__all__ = ["Session", "TenantScope", "User", "get_scope", "get_scope_optional"]
