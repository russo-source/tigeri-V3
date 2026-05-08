"""Create or rotate the platform admin user.

Usage on EC2 after deploying Phase 1+:

    cd /path/to/tigeri
    .venv/bin/python scripts/seed_admin.py

This is idempotent: if `admin@tigeri.ai` already exists in the admin tenant,
it just resets the password to the value below. Rotate the password in this
file (or via TIGERI_ADMIN_PASSWORD env var) and re-run to change it.

The admin user belongs to a dedicated tenant `tnt_admin` (slug `admin`) so
they can sign in across the platform without polluting a customer tenant.
The role 'admin' grants access to the `/admin/*` API routes via the
require_admin gate in src/tigeri/auth/admin.py.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

from tigeri.auth.models import User
from tigeri.auth.passwords import hash_password
from tigeri.core.db import get_sessionmaker
from tigeri.tenant.models import Tenant

ADMIN_TENANT_ID = "tnt_admin"
ADMIN_TENANT_SLUG = "admin"
ADMIN_TENANT_NAME = "Tigeri Platform Admin"

DEFAULT_ADMIN_EMAIL = "admin@tigeri.ai"
# Rotate after first sign-in. Override at runtime with TIGERI_ADMIN_PASSWORD.
# Pilot-default — keep it stable so the operator doesn't have to chase a
# new random string after every seed run. Override with env var when ready
# to enforce strong unique passwords per environment.
DEFAULT_ADMIN_PASSWORD = "PickleJar$"
DEFAULT_ADMIN_NAME = "Tigeri Admin"


async def upsert_admin(
    email: str, password: str, name: str, *, force_change: bool = True
) -> dict[str, str]:
    """Create-or-update the platform admin row.

    ``force_change=True`` (the default) sets ``must_change_password=true`` so
    the next sign-in lands on /change-password. Pass ``False`` only for the
    very first bootstrap when nobody is around to follow up the change."""

    sm = get_sessionmaker()
    async with sm() as session:
        # Ensure the admin tenant exists.
        res = await session.execute(select(Tenant).where(Tenant.id == ADMIN_TENANT_ID))
        tenant = res.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                id=ADMIN_TENANT_ID,
                name=ADMIN_TENANT_NAME,
                slug=ADMIN_TENANT_SLUG,
                region="sg",
                plan="enterprise",
                status="active",
                settings={},
            )
            session.add(tenant)
            await session.flush()

        # Upsert the admin user.
        res = await session.execute(
            select(User)
            .where(User.tenant_id == ADMIN_TENANT_ID)
            .where(User.email == email.lower())
        )
        user = res.scalar_one_or_none()
        if user is None:
            user = User(
                id="usr_admin",
                tenant_id=ADMIN_TENANT_ID,
                email=email.lower(),
                name=name,
                role="admin",
                status="active",
                password_hash=hash_password(password),
                email_verified=True,
                must_change_password=force_change,
            )
            session.add(user)
            verb = "created"
        else:
            user.password_hash = hash_password(password)
            user.role = "admin"
            user.status = "active"
            user.email_verified = True
            user.name = name
            user.must_change_password = force_change
            verb = "updated"

        await session.commit()
        return {
            "verb": verb,
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "user_id": user.id,
            "email": user.email,
            "must_change_password": "true" if force_change else "false",
        }


def main() -> int:
    email = os.environ.get("TIGERI_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    password = os.environ.get("TIGERI_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    name = os.environ.get("TIGERI_ADMIN_NAME", DEFAULT_ADMIN_NAME)
    # Set TIGERI_ADMIN_FORCE_CHANGE=0 only for the very first bootstrap when
    # the operator is signing in themselves and doesn't want to immediately
    # be redirected to /change-password.
    force_change = os.environ.get("TIGERI_ADMIN_FORCE_CHANGE", "1") not in ("0", "false", "no")

    result = asyncio.run(
        upsert_admin(email=email, password=password, name=name, force_change=force_change)
    )
    print(f"  {result['verb']} admin user")
    print(f"     tenant   : {result['tenant_id']}  (slug: {result['tenant_slug']})")
    print(f"     user     : {result['user_id']}")
    print(f"     email    : {result['email']}")
    print("     password : (set; not echoed)")
    print(f"     must_change_password : {result['must_change_password']}")
    print("\nSign in flow:")
    print("  POST /auth/sign-in")
    print(f'  body: {{"tenant_slug":"{result["tenant_slug"]}","email":"{result["email"]}","password":"<password>"}}')
    if result["must_change_password"] == "true":
        print(
            "\nThe sign-in response will carry must_change_password=true and "
            "the API will refuse every authed call except /auth/change-password "
            "until the user picks a new password."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
