"""Seed a demo tenant + demo user for manual smoke testing.

Phase 2 introduced foreign keys from pending_actions / audit_logs / sessions
to tenants(id) and users(id). The original Slice 1 demo flow used
``tnt_demo`` / ``usr_alice`` as free-form header values that never existed
as DB rows; under the new constraints those writes now fail with
ForeignKeyViolationError. Running this script once after a deploy fixes
that by upserting both rows with sensible defaults.

Usage on EC2:
    cd /opt/tigeri
    DBURL=$(sudo grep '^TIGERI_DATABASE_URL=' /etc/tigeri/tigeri.env | cut -d= -f2-)
    sudo -u tigeri bash -c "cd /opt/tigeri && TIGERI_DATABASE_URL='$DBURL' /opt/tigeri/.venv/bin/python scripts/seed_local.py"

Idempotent — re-running just no-ops if rows already exist.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from tigeri.auth.models import User
from tigeri.auth.passwords import hash_password
from tigeri.core.db import get_sessionmaker
from tigeri.tenant.models import Tenant


DEMO_TENANT_ID = "tnt_demo"
DEMO_TENANT_SLUG = "demo"
DEMO_TENANT_NAME = "Demo SME"

DEMO_USER_ID = "usr_alice"
DEMO_USER_EMAIL = "alice@demo.tigeri.ai"
DEMO_USER_NAME = "Alice (demo)"
# A throwaway password — only relevant if someone tries to cookie-auth as
# alice. The Demo tab in the frontend bypasses passwords entirely (header
# auth), so this almost never matters. Rotate before any external use.
DEMO_USER_PASSWORD = "demo-password-change-me"


async def main() -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        # ---------- tenant ----------
        tenant = await session.get(Tenant, DEMO_TENANT_ID)
        if tenant is None:
            tenant = Tenant(
                id=DEMO_TENANT_ID,
                name=DEMO_TENANT_NAME,
                slug=DEMO_TENANT_SLUG,
                region="sg",
                plan="pilot",
                status="active",
                settings={},
                industry="logistics",
                employee_count=80,
                venues_or_locations=4,
                regulated=True,
            )
            session.add(tenant)
            await session.flush()
            print(f"  created tenant {DEMO_TENANT_ID}")
        else:
            # Defensive: if an older row exists with NULL on Phase-2 columns,
            # backfill so FKs and queries don't trip up.
            tenant.slug = tenant.slug or DEMO_TENANT_SLUG
            tenant.region = tenant.region or "sg"
            tenant.plan = tenant.plan or "pilot"
            tenant.status = tenant.status or "active"
            tenant.settings = tenant.settings or {}
            print(f"  tenant {DEMO_TENANT_ID} already exists (backfilled if needed)")

        # ---------- user ----------
        res = await session.execute(
            select(User)
            .where(User.tenant_id == DEMO_TENANT_ID)
            .where(User.id == DEMO_USER_ID)
        )
        user = res.scalar_one_or_none()
        if user is None:
            user = User(
                id=DEMO_USER_ID,
                tenant_id=DEMO_TENANT_ID,
                email=DEMO_USER_EMAIL,
                name=DEMO_USER_NAME,
                role="member",
                status="active",
                password_hash=hash_password(DEMO_USER_PASSWORD),
                email_verified=True,
            )
            session.add(user)
            print(f"  created user {DEMO_USER_ID}")
        else:
            print(f"  user {DEMO_USER_ID} already exists")

        await session.commit()

    print(
        "\nDemo flow ready. Sign in via the Demo tab with tenant_id=tnt_demo, "
        "user_id=usr_alice, OR via Account with the password printed above."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
