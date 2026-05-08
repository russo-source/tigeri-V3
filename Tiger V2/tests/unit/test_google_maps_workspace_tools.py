"""Unit tests for the Maps + Sheets/Drive tool wrappers.

We mock the underlying clients (`tigeri.integrations.google_maps` and
`GoogleClient.for_tenant`) so the tests stay offline and deterministic. The
HTTP layer is intentionally untested here — the wrappers' job is to validate
input, surface errors as structured dicts, and pass the cleaned args
through to the client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tigeri.agents.orchestrator import tools


# ---- Maps -------------------------------------------------------------


@pytest.mark.asyncio
async def test_geocode_address_passes_through():
    with patch(
        "tigeri.integrations.google_maps.geocode",
        new=AsyncMock(
            return_value={
                "ok": True,
                "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA",
                "place_id": "ChIJ_abc",
                "lat": 37.4220,
                "lng": -122.0841,
                "types": ["street_address"],
            }
        ),
    ):
        out = await tools.geocode_address({"address": "googleplex"})
    assert out["ok"] is True
    assert out["lat"] == 37.4220


@pytest.mark.asyncio
async def test_geocode_address_validates_required_field():
    out = await tools.geocode_address({"address": ""})
    assert "error" in out


@pytest.mark.asyncio
async def test_maps_tools_surface_unconfigured_cleanly():
    """When GOOGLE_MAPS_API_KEY is empty, the underlying client raises
    MapsNotConfigured. The tool wrapper must convert that to a structured
    error dict, not propagate the exception (which would crash the chat)."""

    from tigeri.integrations.google_maps import MapsNotConfigured

    with patch(
        "tigeri.integrations.google_maps.find_place",
        new=AsyncMock(side_effect=MapsNotConfigured("Maps API key not configured.")),
    ):
        out = await tools.find_place({"query": "Acme Sydney"})

    assert "error" in out
    assert "Maps API key not configured" in out["error"]


@pytest.mark.asyncio
async def test_compute_travel_time_validates_origins_and_destinations():
    out = await tools.compute_travel_time({"origins": [], "destinations": ["x"]})
    assert "error" in out
    out2 = await tools.compute_travel_time({"origins": ["x"], "destinations": []})
    assert "error" in out2


@pytest.mark.asyncio
async def test_compute_travel_time_passes_mode_through():
    with patch(
        "tigeri.integrations.google_maps.distance_matrix",
        new=AsyncMock(return_value={"ok": True, "mode": "transit", "results": []}),
    ) as fake:
        out = await tools.compute_travel_time(
            {"origins": ["A"], "destinations": ["B"], "mode": "transit"}
        )
    assert out["ok"] is True
    assert fake.await_args.kwargs["mode"] == "transit"


# ---- Sheets / Drive ---------------------------------------------------


@pytest.mark.asyncio
async def test_read_sheet_returns_row_count():
    fake_client = MagicMock()
    fake_client.read_sheet = AsyncMock(
        return_value=[
            ["vendor", "amount"],
            ["Acme", "5000"],
            ["Beta", "120"],
        ]
    )
    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.read_sheet(
            {"spreadsheet_id": "abc123", "range_a1": "Sheet1!A1:B3"},
            session=MagicMock(),
            tenant_id="tnt_admin",
        )
    assert out["ok"] is True
    assert out["row_count"] == 3
    assert out["rows"][1] == ["Acme", "5000"]


@pytest.mark.asyncio
async def test_read_sheet_validates_args():
    out = await tools.read_sheet(
        {"spreadsheet_id": "", "range_a1": "Sheet1"},
        session=MagicMock(),
        tenant_id="tnt_admin",
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_append_sheet_row_validates_values_shape():
    out = await tools.append_sheet_row(
        {"spreadsheet_id": "abc", "range_a1": "Sheet1", "values": "not-a-list"},
        session=MagicMock(),
        tenant_id="tnt_admin",
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_append_sheet_row_returns_update_summary():
    fake_client = MagicMock()
    fake_client.append_sheet_row = AsyncMock(
        return_value={
            "spreadsheet_id": "abc",
            "updated_range": "Sheet1!A4:C4",
            "updated_rows": 1,
            "updated_cells": 3,
        }
    )
    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.append_sheet_row(
            {
                "spreadsheet_id": "abc",
                "range_a1": "Sheet1",
                "values": [["2026-04-28", "ABC Ltd", 5000]],
            },
            session=MagicMock(),
            tenant_id="tnt_admin",
        )
    assert out["ok"] is True
    assert out["updated_rows"] == 1
    assert out["updated_cells"] == 3


@pytest.mark.asyncio
async def test_create_drive_doc_returns_view_link():
    fake_client = MagicMock()
    fake_client.create_drive_doc = AsyncMock(
        return_value={
            "id": "1abcDEF",
            "name": "Q2 Report",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/1abcDEF/edit",
        }
    )
    with patch(
        "tigeri.integrations.google.GoogleClient.for_tenant",
        new=AsyncMock(return_value=fake_client),
    ):
        out = await tools.create_drive_doc(
            {"title": "Q2 Report", "body": "<h1>Numbers</h1>"},
            session=MagicMock(),
            tenant_id="tnt_admin",
        )
    assert out["ok"] is True
    assert out["file_id"] == "1abcDEF"
    assert "docs.google.com" in out["web_view_link"]


@pytest.mark.asyncio
async def test_create_drive_doc_rejects_unsupported_mime():
    out = await tools.create_drive_doc(
        {"title": "x", "body": "y", "mime_type": "application/pdf"},
        session=MagicMock(),
        tenant_id="tnt_admin",
    )
    assert "error" in out


def test_new_tools_are_registered_and_classified():
    schema_names = {s["name"] for s in tools.TOOL_SCHEMAS}
    for name in (
        "geocode_address",
        "find_place",
        "compute_travel_time",
        "get_weather",
        "read_sheet",
        "append_sheet_row",
        "create_drive_doc",
    ):
        assert name in schema_names, f"missing {name} from TOOL_SCHEMAS"
        assert name in tools.REGISTRY, f"missing {name} from REGISTRY"

    # Reads bypass the propose/confirm gate; writes must go through it.
    for name in (
        "geocode_address",
        "find_place",
        "compute_travel_time",
        "get_weather",
        "read_sheet",
    ):
        assert name not in tools.WRITE_TOOLS, f"{name} should not be a write"
    for name in ("append_sheet_row", "create_drive_doc"):
        assert name in tools.WRITE_TOOLS, f"{name} should be a write"


@pytest.mark.asyncio
async def test_get_weather_geocodes_address_first_then_calls_weather():
    """When called with an address, the tool should geocode → current →
    forecast in that order, and return a unified shape."""

    with (
        patch(
            "tigeri.integrations.google_maps.geocode",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "lat": -33.8688,
                    "lng": 151.2093,
                    "formatted_address": "Sydney NSW, Australia",
                }
            ),
        ),
        patch(
            "tigeri.integrations.google_maps.weather_current",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "lat": -33.8688,
                    "lng": 151.2093,
                    "is_daytime": True,
                    "condition": "Partly cloudy",
                    "temperature_c": 22.0,
                }
            ),
        ),
        patch(
            "tigeri.integrations.google_maps.weather_forecast",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "forecast": [
                        {"date": "2026-04-29", "condition": "Sunny", "max_c": 24, "min_c": 15},
                    ],
                }
            ),
        ),
    ):
        out = await tools.get_weather({"address": "Sydney", "days": 1})

    assert out["ok"] is True
    assert out["lat"] == -33.8688
    assert out["resolved_address"] == "Sydney NSW, Australia"
    assert out["current"]["condition"] == "Partly cloudy"
    assert isinstance(out["forecast"], list)
    assert out["forecast"][0]["condition"] == "Sunny"


@pytest.mark.asyncio
async def test_get_weather_validates_inputs():
    out = await tools.get_weather({})  # neither address nor lat+lng
    assert "error" in out
