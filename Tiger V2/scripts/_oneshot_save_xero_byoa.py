"""One-shot helper: save BYOA OAuth client credentials for a tenant×provider
and (optionally) clear the stale OAuth token row so the next connect kicks
off a fresh consent flow.

Usage:
    TIGERI_DATABASE_URL=postgresql+asyncpg://... \
    TIGERI_SECRET_ENCRYPTION_KEY=... \
    BYOA_TENANT=tnt_admin BYOA_PROVIDER=xero \
    BYOA_CLIENT_ID=... BYOA_CLIENT_SECRET=... \
    python scripts/_oneshot_save_xero_byoa.py

Idempotent: re-running rewrites the same row in tenant_integration_credentials.
Reads credentials from env vars only — never hardcode them in this file."""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Import every model that participates in the FK graph touched by
# tenant_integration_credentials so SQLAlchemy can resolve `tenants` /
# `users` referents at flush time.
from tigeri.auth.models import Session as _US, User as _U  # noqa: F401
from tigeri.integrations import tenant_creds
from tigeri.integrations.models import TenantIntegration
from tigeri.tenant.models import Tenant as _T  # noqa: F401


async def main() -> int:
    db_url = os.environ.get("TIGERI_DATABASE_URL")
    tenant = os.environ.get("BYOA_TENANT")
    provider = os.environ.get("BYOA_PROVIDER")
    client_id = os.environ.get("BYOA_CLIENT_ID")
    client_secret = os.environ.get("BYOA_CLIENT_SECRET")

    missing = [
        name
        for name, val in (
            ("TIGERI_DATABASE_URL", db_url),
            ("BYOA_TENANT", tenant),
            ("BYOA_PROVIDER", provider),
            ("BYOA_CLIENT_ID", client_id),
            ("BYOA_CLIENT_SECRET", client_secret),
        )
        if not val
    ]
    if missing:
        print(f"missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    engine = create_async_engine(db_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as db:
        await tenant_creds.save(
            db,
            tenant_id=tenant,
            provider=provider,
            client_id=client_id,
            client_secret=client_secret,
        )
        # Clear any existing OAuth session — old tokens were issued by the
        # previous app's client_id and will 401 on first refresh against
        # the new one. Wiping forces a clean reconnect. Skip with
        # BYOA_KEEP_TOKENS=1 if the user is just rotating secrets on the
        # same Xero/QB/etc. app.
        if os.environ.get("BYOA_KEEP_TOKENS") not in ("1", "true", "yes"):
            existing = await db.scalar(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == tenant,
                    TenantIntegration.provider == provider,
                )
            )
            if existing is not None:
                await db.execute(
                    delete(TenantIntegration).where(
                        TenantIntegration.tenant_id == tenant,
                        TenantIntegration.provider == provider,
                    )
                )
                print(f"  cleared existing token row id={existing.id}")
        await db.commit()
        print(f"  saved BYOA: {tenant}/{provider} client_id={client_id[:8]}…")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
