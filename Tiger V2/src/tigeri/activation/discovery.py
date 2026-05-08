import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import httpx

from tigeri.core.config import get_settings
from tigeri.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CapabilityInventory:
    """Output of S3 in section 4.2 of the catalog."""

    tenant_id: str
    source_system: str
    access_mode: Literal["MCP", "API"]
    discovered_objects: list[str] = field(default_factory=list)
    discovered_actions: list[str] = field(default_factory=list)
    auth_scopes: list[str] = field(default_factory=list)
    introspection_completed_at: str = ""


class DiscoveryError(Exception):
    pass


class CRMUnreachable(DiscoveryError):
    pass


class IntrospectionTimeout(DiscoveryError):
    pass


@dataclass
class CRMHandle:
    """Tenant-supplied CRM connection metadata."""

    source_system: str
    api_base_url: str | None = None
    mcp_endpoint: str | None = None
    auth_header: dict[str, str] | None = None


async def _discover_via_mcp(handle: CRMHandle, tenant_id: str) -> CapabilityInventory:
    """Try MCP first, per section 4.2 'Use MCP if the CRM has MCP accessibility else API'."""

    if not handle.mcp_endpoint:
        raise DiscoveryError("no MCP endpoint configured")

    timeout = get_settings().discovery_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{handle.mcp_endpoint}/list_tools",
                    headers=handle.auth_header or {},
                    json={"tenant_id": tenant_id},
                )
                resp.raise_for_status()
                tools_payload = resp.json()
    except TimeoutError as e:
        raise IntrospectionTimeout("MCP introspection timed out") from e
    except httpx.HTTPError as e:
        raise DiscoveryError(f"MCP introspection failed: {e}") from e

    return CapabilityInventory(
        tenant_id=tenant_id,
        source_system=handle.source_system,
        access_mode="MCP",
        discovered_objects=tools_payload.get("resources", []),
        discovered_actions=tools_payload.get("tools", []),
        auth_scopes=tools_payload.get("scopes", []),
        introspection_completed_at=datetime.now(UTC).isoformat(),
    )


async def _discover_via_api(handle: CRMHandle, tenant_id: str) -> CapabilityInventory:
    if not handle.api_base_url:
        raise CRMUnreachable("no API endpoint configured")

    timeout = get_settings().discovery_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"{handle.api_base_url}/introspect",
                    headers=handle.auth_header or {},
                )
                resp.raise_for_status()
                payload = resp.json()
    except TimeoutError as e:
        raise IntrospectionTimeout("API introspection timed out") from e
    except httpx.HTTPError as e:
        raise CRMUnreachable(f"API unreachable: {e}") from e

    return CapabilityInventory(
        tenant_id=tenant_id,
        source_system=handle.source_system,
        access_mode="API",
        discovered_objects=payload.get("object_types", []),
        discovered_actions=payload.get("endpoints", []),
        auth_scopes=payload.get("scopes", []),
        introspection_completed_at=datetime.now(UTC).isoformat(),
    )


async def discover(handle: CRMHandle, tenant_id: str) -> CapabilityInventory:
    """Section 4.2 contract: MCP first, API fallback."""

    if handle.mcp_endpoint:
        try:
            return await _discover_via_mcp(handle, tenant_id)
        except IntrospectionTimeout:
            logger.warning("mcp_introspection_timeout_falling_back_to_api", tenant_id=tenant_id)
        except DiscoveryError as e:
            logger.warning("mcp_failed_falling_back_to_api", tenant_id=tenant_id, error=str(e))
    return await _discover_via_api(handle, tenant_id)
