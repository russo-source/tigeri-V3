"""Thin async client for Google Maps Platform — Geocoding, Places, Distance Matrix.

Uses a server-side API key (``settings.google_maps_api_key``) — no per-tenant
OAuth needed. Restrict the key to the EC2 instance's IP in the Google Cloud
Console; do not expose it to browsers.

Each method returns a structured Python dict and translates Google's status
strings into either ``{"ok": True, ...}`` or ``{"error": "<human msg>"}``.
The orchestrator tools pass these straight back to the LLM, so the shapes
need to be small and uniform."""

from __future__ import annotations

from typing import Any

import httpx

from tigeri.core.config import get_settings


GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Places API (New) — v1 endpoint at places.googleapis.com. Different request
# shape (POST with JSON body, X-Goog-Api-Key + X-Goog-FieldMask headers)
# than the legacy maps.googleapis.com/maps/api/place/* endpoints. The newer
# API is what Google asks new projects to enable, so we standardise on it.
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
# Weather API — part of Maps Platform, GA in 2025. Read-only, key-auth via
# the standard ``key`` query param.
WEATHER_CURRENT_URL = "https://weather.googleapis.com/v1/currentConditions:lookup"
WEATHER_FORECAST_URL = "https://weather.googleapis.com/v1/forecast/days:lookup"


class MapsNotConfigured(Exception):
    """Raised when GOOGLE_MAPS_API_KEY is empty. Tool wrappers catch this and
    return a user-readable error so the LLM can suggest configuring the key."""


def _api_key() -> str:
    key = get_settings().google_maps_api_key
    if not key:
        raise MapsNotConfigured(
            "Google Maps API key not configured. Set GOOGLE_MAPS_API_KEY "
            "in /etc/tigeri/tigeri.env (server-side, IP-restricted)."
        )
    return key


async def geocode(address: str) -> dict[str, Any]:
    """Forward-geocode a free-text address. Returns the top match's lat/lng,
    canonical formatted address, place_id, and component types."""

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            GEOCODE_URL,
            params={"address": address, "key": _api_key()},
        )
        resp.raise_for_status()
        body = resp.json()

    status = body.get("status", "")
    if status != "OK":
        return {
            "ok": False,
            "error": f"Geocoding returned {status}: {body.get('error_message', '')}".strip(),
        }
    results = body.get("results") or []
    if not results:
        return {"ok": False, "error": "no results"}
    top = results[0]
    loc = (top.get("geometry") or {}).get("location") or {}
    return {
        "ok": True,
        "formatted_address": top.get("formatted_address", ""),
        "place_id": top.get("place_id", ""),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "types": top.get("types", []),
    }


async def find_place(query: str) -> dict[str, Any]:
    """Find a place by free-text query (e.g. 'Acme Pty Ltd Sydney') using
    Places API (New) Text Search. Returns the top hit with name, address,
    location, rating, opening status, and place_id.

    The new API requires:
    - POST with JSON body ``{"textQuery": "..."}``
    - ``X-Goog-Api-Key`` header (key in header, not query string)
    - ``X-Goog-FieldMask`` header listing the fields we want — the API
      defaults to returning *no* fields if you don't specify, which catches
      every new caller out at least once.
    """

    field_mask = (
        "places.id,places.displayName,places.formattedAddress,"
        "places.location,places.rating,places.regularOpeningHours.openNow,"
        "places.types"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            PLACES_TEXT_SEARCH_URL,
            headers={
                "X-Goog-Api-Key": _api_key(),
                "X-Goog-FieldMask": field_mask,
                "Content-Type": "application/json",
            },
            json={"textQuery": query, "maxResultCount": 1},
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"Places(New) HTTP {resp.status_code}: {resp.text[:300]}",
            }
        body = resp.json()

    places = body.get("places") or []
    if not places:
        return {"ok": False, "error": "no results"}
    top = places[0]
    loc = top.get("location") or {}
    return {
        "ok": True,
        "place_id": top.get("id", ""),
        "name": (top.get("displayName") or {}).get("text", ""),
        "formatted_address": top.get("formattedAddress", ""),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "rating": top.get("rating"),
        "open_now": ((top.get("regularOpeningHours") or {}).get("openNow")),
        "types": top.get("types", []),
    }


async def distance_matrix(
    origins: list[str],
    destinations: list[str],
    *,
    mode: str = "driving",
    departure_time: str | None = None,
) -> dict[str, Any]:
    """Travel time + distance for every (origin, destination) pair. Origins
    and destinations are free-text addresses or 'lat,lng' strings.

    `mode` is one of {driving, walking, bicycling, transit}.
    `departure_time` is "now" or a Unix timestamp string (driving + transit
    only; enables traffic-aware estimates)."""

    if not origins or not destinations:
        return {"ok": False, "error": "origins and destinations are both required"}
    if mode not in {"driving", "walking", "bicycling", "transit"}:
        return {"ok": False, "error": f"unsupported travel mode {mode!r}"}

    params: dict[str, Any] = {
        "origins": "|".join(origins),
        "destinations": "|".join(destinations),
        "mode": mode,
        "key": _api_key(),
    }
    if departure_time and mode in {"driving", "transit"}:
        params["departure_time"] = departure_time

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(DISTANCE_MATRIX_URL, params=params)
        resp.raise_for_status()
        body = resp.json()

    if body.get("status") != "OK":
        return {
            "ok": False,
            "error": f"Distance Matrix returned {body.get('status')}: {body.get('error_message', '')}".strip(),
        }

    matrix: list[dict[str, Any]] = []
    rows = body.get("rows") or []
    for o_idx, row in enumerate(rows):
        for d_idx, element in enumerate(row.get("elements") or []):
            if element.get("status") != "OK":
                matrix.append(
                    {
                        "origin": origins[o_idx],
                        "destination": destinations[d_idx],
                        "ok": False,
                        "error": element.get("status"),
                    }
                )
                continue
            duration = element.get("duration_in_traffic") or element.get("duration") or {}
            distance = element.get("distance") or {}
            matrix.append(
                {
                    "origin": origins[o_idx],
                    "destination": destinations[d_idx],
                    "ok": True,
                    "duration_text": duration.get("text"),
                    "duration_seconds": duration.get("value"),
                    "distance_text": distance.get("text"),
                    "distance_meters": distance.get("value"),
                }
            )
    return {"ok": True, "mode": mode, "results": matrix}


async def weather_current(lat: float, lng: float) -> dict[str, Any]:
    """Current observed weather at a lat/lng (Google Weather API)."""

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            WEATHER_CURRENT_URL,
            params={
                "key": _api_key(),
                "location.latitude": str(lat),
                "location.longitude": str(lng),
            },
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"Weather HTTP {resp.status_code}: {resp.text[:300]}",
            }
        body = resp.json()

    temp = (body.get("temperature") or {})
    feels = (body.get("feelsLikeTemperature") or {})
    wind = ((body.get("wind") or {}).get("speed") or {})
    return {
        "ok": True,
        "lat": lat,
        "lng": lng,
        "is_daytime": body.get("isDaytime"),
        "condition": (body.get("weatherCondition") or {}).get("description", {}).get("text", ""),
        "temperature_c": temp.get("degrees"),
        "feels_like_c": feels.get("degrees"),
        "humidity_pct": (body.get("relativeHumidity")),
        "wind_speed_kph": wind.get("value"),
        "wind_unit": wind.get("unit"),
        "precip_pct": (body.get("precipitation") or {}).get("probability", {}).get("percent"),
        "uv_index": body.get("uvIndex"),
        "as_of": body.get("currentTime"),
    }


async def weather_forecast(
    lat: float, lng: float, days: int = 5
) -> dict[str, Any]:
    """Multi-day forecast (Google Weather API). ``days`` clamped to 1..10."""

    days = max(1, min(int(days), 10))
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            WEATHER_FORECAST_URL,
            params={
                "key": _api_key(),
                "location.latitude": str(lat),
                "location.longitude": str(lng),
                "days": str(days),
            },
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"Weather forecast HTTP {resp.status_code}: {resp.text[:300]}",
            }
        body = resp.json()

    forecasts = body.get("forecastDays") or []
    summaries: list[dict[str, Any]] = []
    for day in forecasts:
        date = (day.get("displayDate") or {})
        max_temp = (day.get("maxTemperature") or {})
        min_temp = (day.get("minTemperature") or {})
        condition = (day.get("daytimeForecast") or {}).get("weatherCondition") or {}
        summaries.append(
            {
                "date": f"{date.get('year')}-{date.get('month'):02d}-{date.get('day'):02d}"
                if date.get("year")
                else "",
                "condition": condition.get("description", {}).get("text", ""),
                "max_c": max_temp.get("degrees"),
                "min_c": min_temp.get("degrees"),
                "precip_pct": (
                    (day.get("daytimeForecast") or {})
                    .get("precipitation", {})
                    .get("probability", {})
                    .get("percent")
                ),
            }
        )
    return {"ok": True, "lat": lat, "lng": lng, "days": days, "forecast": summaries}
