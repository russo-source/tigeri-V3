"""Contain integration resolver backend logic."""
import logging
from config.db_pool import get_conn
logger = logging.getLogger(__name__)

# Constant for provider groups.
PROVIDER_GROUPS = {
    "calendar":   ["google", "outlook"],
    "email":      ["google", "outlook"],
    "accounting": ["xero", "quickbooks"],
    "storage":    ["google", "outlook"],
    "payment":    ["stripe", "paypal"],
}


def resolve_provider(client_id: str, category: str) -> str:
    """Resolve provider."""
    providers = PROVIDER_GROUPS.get(category)
    if not providers:
        raise ValueError(f"Unknown integration category: '{category}'")

    try:
        
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET LOCAL statement_timeout = '3000'")
            cur.execute(
                """
                SELECT provider FROM client_integrations
                WHERE client_id = %s
                  AND connected = TRUE
                  AND provider = ANY(%s)
                  AND meta IS NOT NULL
                  AND meta != '{}'::jsonb
                ORDER BY connected_at DESC LIMIT 1
                """,
                (client_id, providers),
            )
            row = cur.fetchone()
            cur.close()
    except Exception as e:
        logger.error("resolve_provider DB error client=%s category=%s: %s", client_id, category, e)
        raise ValueError(
            f"Could not check {category} integration — database unavailable. Please try again."
        )

    if not row:
        raise ValueError(
            f"No connected {category} integration for this account. "
            "Please connect one in Settings → Integrations."
        )

    logger.info("resolve_provider client=%s category=%s → %s", client_id, category, row[0])
    return row[0]


def resolve_storage_provider(client_id: str) -> str:
    """
    Resolve the correct storage backend string for a client.
    """
    try:
        from config.client_config import get_client_config
        config = get_client_config(client_id)
        explicit = config.get("storage_backend", "").lower().strip()
        if explicit in ("google_drive", "sharepoint", "onedrive"):
            logger.debug(
                "resolve_storage_provider: explicit override '%s' client=%s", explicit, client_id
            )
            return explicit
    except Exception as e:
        logger.debug("resolve_storage_provider: client config unavailable client=%s: %s", client_id, e)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET LOCAL statement_timeout = '3000'")
            cur.execute(
                """
                SELECT provider FROM client_integrations
                WHERE client_id = %s AND connected = TRUE
                  AND provider = ANY(%s)
                ORDER BY connected_at DESC LIMIT 1
                """,
                (client_id, ["google", "outlook"]),
            )
            row = cur.fetchone()
            cur.close()
    except Exception as e:
        logger.error("resolve_storage_provider DB error client=%s: %s", client_id, e)
        raise ValueError(
            "Could not check storage integration — database unavailable. Please try again."
        )

    if not row:
        raise ValueError(
            "No storage integration connected. "
            "Please connect Google Drive, OneDrive, or SharePoint in Settings → Integrations."
        )

    provider = row[0]

    if provider == "google":
        return "google_drive"

    if provider == "outlook":
        try:
            from webhooks.integrations import get_provider_meta
            meta = get_provider_meta(client_id, "outlook")
        except Exception as e:
            logger.error(
                "resolve_storage_provider: could not read provider meta client=%s: %s",
                client_id, e,
            )
            raise ValueError(
                "Could not determine your Microsoft storage type (SharePoint vs OneDrive) — "
                "please reconnect your Microsoft 365 integration in Settings → Integrations."
            )

        if meta.get("sharepoint_site_id"):
            return "sharepoint"
        return "onedrive"

    raise ValueError(
        f"Unrecognised storage provider '{provider}'. "
        "Please reconnect your storage integration in Settings → Integrations."
    )