"""Unit tests for tigeri.tenant.preferences — the JSON settings reader.

Covers: timezone default (Asia/Singapore), tenant override read, missing
tenant safe fallback, gmail signature default + override.
"""

from __future__ import annotations

import pytest

from tigeri.tenant.models import Tenant
from tigeri.tenant.preferences import (
    DEFAULT_GMAIL_SIGNATURE,
    DEFAULT_TIMEZONE,
    get_gmail_signature,
    get_timezone,
)


@pytest.mark.asyncio
async def test_timezone_defaults_to_singapore_when_unset(session):
    t = Tenant(id="tnt_t1", name="T1", slug="t1", settings={})
    session.add(t)
    await session.flush()

    tz = await get_timezone(session, "tnt_t1")
    assert tz == "Asia/Singapore"
    assert DEFAULT_TIMEZONE == "Asia/Singapore"


@pytest.mark.asyncio
async def test_timezone_reads_tenant_override(session):
    t = Tenant(
        id="tnt_t2", name="T2", slug="t2", settings={"timezone": "Europe/London"}
    )
    session.add(t)
    await session.flush()

    tz = await get_timezone(session, "tnt_t2")
    assert tz == "Europe/London"


@pytest.mark.asyncio
async def test_timezone_falls_back_when_tenant_missing(session):
    tz = await get_timezone(session, "tnt_does_not_exist")
    assert tz == DEFAULT_TIMEZONE


@pytest.mark.asyncio
async def test_timezone_ignores_blank_override(session):
    t = Tenant(id="tnt_t3", name="T3", slug="t3", settings={"timezone": "   "})
    session.add(t)
    await session.flush()

    tz = await get_timezone(session, "tnt_t3")
    assert tz == DEFAULT_TIMEZONE


@pytest.mark.asyncio
async def test_gmail_signature_default_is_empty(session):
    t = Tenant(id="tnt_t4", name="T4", slug="t4", settings={})
    session.add(t)
    await session.flush()

    sig = await get_gmail_signature(session, "tnt_t4")
    assert sig == ""
    assert DEFAULT_GMAIL_SIGNATURE == ""


@pytest.mark.asyncio
async def test_gmail_signature_reads_override(session):
    t = Tenant(
        id="tnt_t5",
        name="T5",
        slug="t5",
        settings={"gmail_signature": "— sent via Tigeri"},
    )
    session.add(t)
    await session.flush()

    sig = await get_gmail_signature(session, "tnt_t5")
    assert sig == "— sent via Tigeri"
