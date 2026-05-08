"""Per-tenant OAuth client credentials (Bring Your Own App).

By default, Tigeri operates a single OAuth client per provider (the platform
client_id/secret loaded from env). Enterprise customers often want to bring
their *own* app registration so:
  - the connection inherits their corporate compliance / branding
  - data flows through their provider tenant, not Tigeri's
  - they can revoke the app independently of all other Tigeri customers
  - they can pin specific scopes or redirect URIs

This module stores per-tenant credentials encrypted at rest (Fernet via
TIGERI_SECRET_ENCRYPTION_KEY) and provides ``resolve()`` — returns the
tenant's credentials if configured, else falls back to the platform default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.config import get_settings
from tigeri.core.db import Base
from tigeri.core.ids import new_id
from tigeri.integrations.encryption import decrypt, encrypt

# Providers that support BYOA. Telegram + WhatsApp are excluded — Telegram
# uses a single platform bot token (not OAuth), WhatsApp is currently
# routed through 360dialog with platform credentials.
SUPPORTED_PROVIDERS = {"xero", "quickbooks", "google", "microsoft", "paypal"}


class TenantIntegrationCredentials(Base):
    """Per-tenant OAuth client credentials (one row per tenant×provider)."""

    __tablename__ = "tenant_integration_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", name="uq_tenant_integration_credentials"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    client_secret_enc: Mapped[str] = mapped_column(String(2048), nullable=False)
    custom_redirect_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Scope override — JSON array of strings. NULL means use provider default.
    custom_scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Provider-specific extras (e.g., xero_tenant_id pin, qb_environment).
    extra_meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


@dataclass(slots=True)
class ResolvedCreds:
    """Effective OAuth credentials for one tenant×provider.

    ``source`` is "tenant" if the tenant's row is in use, "platform" if the
    env-default applied. The frontend surfaces this so admins know whether
    they're on their own app or the shared one.
    """

    client_id: str
    client_secret: str
    redirect_uri: str | None  # None means caller computes from settings
    scopes: list[str] | None
    source: str  # "tenant" | "platform"


# ---- CRUD ----------------------------------------------------------------


async def get(
    db: AsyncSession, *, tenant_id: str, provider: str
) -> TenantIntegrationCredentials | None:
    if provider not in SUPPORTED_PROVIDERS:
        return None
    res = await db.execute(
        select(TenantIntegrationCredentials)
        .where(TenantIntegrationCredentials.tenant_id == tenant_id)
        .where(TenantIntegrationCredentials.provider == provider)
    )
    return res.scalar_one_or_none()


async def save(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    client_id: str,
    client_secret: str,
    custom_redirect_uri: str | None = None,
    custom_scopes: list[str] | None = None,
    extra_meta: dict | None = None,
) -> TenantIntegrationCredentials:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"BYOA not supported for provider {provider!r}")
    if not client_id or not client_secret:
        raise ValueError("client_id and client_secret are required")

    enc_secret = encrypt(client_secret)
    row = await get(db, tenant_id=tenant_id, provider=provider)
    if row is None:
        row = TenantIntegrationCredentials(
            id=new_id("itc"),
            tenant_id=tenant_id,
            provider=provider,
            client_id=client_id,
            client_secret_enc=enc_secret,
            custom_redirect_uri=custom_redirect_uri,
            custom_scopes=custom_scopes,
            extra_meta=extra_meta or {},
        )
        db.add(row)
    else:
        row.client_id = client_id
        row.client_secret_enc = enc_secret
        row.custom_redirect_uri = custom_redirect_uri
        row.custom_scopes = custom_scopes
        if extra_meta is not None:
            row.extra_meta = extra_meta
    await db.flush()
    return row


async def remove(db: AsyncSession, *, tenant_id: str, provider: str) -> bool:
    res = await db.execute(
        delete(TenantIntegrationCredentials)
        .where(TenantIntegrationCredentials.tenant_id == tenant_id)
        .where(TenantIntegrationCredentials.provider == provider)
    )
    return (res.rowcount or 0) > 0


# ---- Resolution ---------------------------------------------------------


def _platform_creds(provider: str) -> tuple[str, str]:
    """Look up the platform-default client_id/secret from settings."""
    s = get_settings()
    if provider == "xero":
        return s.xero_client_id, s.xero_client_secret
    if provider == "quickbooks":
        return s.quickbooks_client_id, s.quickbooks_client_secret
    if provider == "google":
        return s.google_client_id, s.google_client_secret
    if provider == "microsoft":
        return s.microsoft_client_id, s.microsoft_client_secret_value
    if provider == "paypal":
        return s.paypal_client_id, s.paypal_client_secret
    return "", ""


async def resolve(
    db: AsyncSession, *, tenant_id: str, provider: str
) -> ResolvedCreds:
    """Effective OAuth client credentials for this tenant×provider.

    Tenant-managed > platform default. Raises ValueError if neither is
    configured (lets the caller surface a helpful message).
    """
    row = await get(db, tenant_id=tenant_id, provider=provider)
    if row is not None:
        return ResolvedCreds(
            client_id=row.client_id,
            client_secret=decrypt(row.client_secret_enc),
            redirect_uri=row.custom_redirect_uri,
            scopes=row.custom_scopes,
            source="tenant",
        )

    plat_id, plat_secret = _platform_creds(provider)
    if not plat_id or not plat_secret:
        raise ValueError(
            f"No OAuth credentials configured for provider {provider!r}. "
            "Either the platform admin must set the env vars, or this tenant "
            "must save their own client_id / client_secret via "
            "PUT /v1/integrations/{provider}/config."
        )
    return ResolvedCreds(
        client_id=plat_id,
        client_secret=plat_secret,
        redirect_uri=None,
        scopes=None,
        source="platform",
    )
