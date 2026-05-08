"""Contain google calendar backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)


class GoogleCalendarIntegration:

    """Represent the GoogleCalendarIntegration component and its related behavior."""
    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id

    @property
    def headers(self) -> dict:
        """Execute headers for GoogleCalendarIntegration."""
        from integrations.token_manager import _get_valid_token
        token = _get_valid_token("google", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def check_availability(self, date: str, time: str, duration_minutes: int = 60, timezone: str = "UTC") -> dict:
        return self._check_availability(date, time, duration_minutes, timezone)

    def _check_availability(self, date: str, time: str, duration_minutes: int, timezone: str = "UTC") -> dict:
        import pytz
        from datetime import datetime, timedelta
        try:
            local_tz = pytz.timezone(timezone)
            naive_start = datetime.strptime(f"{date}T{time}", "%Y-%m-%dT%H:%M")
            start_utc = local_tz.localize(naive_start).astimezone(pytz.utc)
            end_utc = start_utc + timedelta(minutes=duration_minutes)

            response = httpx.post(
                f"{self.BASE_URL}/freeBusy",
                headers=self.headers,
                json={
                    "timeMin": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "timeMax": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "items": [{"id": "primary"}],
                },
                timeout=10,
            )
            response.raise_for_status()
            busy = response.json().get("calendars", {}).get("primary", {}).get("busy", [])
            return {"available": len(busy) == 0, "conflicts": busy}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Google Calendar auth expired — please reconnect Google in integrations."}
            logger.error("[%s] check_availability failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Google Calendar error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] check_availability network error: %s", self.client_id, e)
            return {"error": f"Google Calendar unreachable: {e}"}

    def create_event(self, data: dict) -> dict:
        """Create event."""
        return self._create_event(data)

    def _create_event(self, data: dict) -> dict:
        """Create event."""
        timezone = data.get("timezone", "UTC")
        payload = {
            "summary": data.get("subject", "Meeting"),
            "description": data.get("description", ""),
            "start": {"dateTime": data.get("start"), "timeZone": timezone},
            "end": {"dateTime": data.get("end"), "timeZone": timezone},
            "attendees": [{"email": a} for a in data.get("attendees", []) if a],
            "sendUpdates": "all",
        }
        try:
            response = httpx.post(
                f"{self.BASE_URL}/calendars/primary/events",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            if not result:
                return {"error": "Empty response from Google Calendar."}
            return {
                "event_id": result.get("id", ""),
                "title": result.get("summary", ""),
                "start": result.get("start", {}).get("dateTime", data.get("start", "")),
                "end": result.get("end", {}).get("dateTime", data.get("end", "")),
                "link": result.get("htmlLink", ""),
                "teams_link": "",
                "attendees": [a.get("email") for a in result.get("attendees", [])],
                "provider": "google",
                "timezone": timezone,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Google Calendar auth expired — please reconnect Google in integrations."}
            logger.error("[%s] create_event failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Google Calendar error: {e.response.status_code} — {e.response.text}"}
        except httpx.HTTPError as e:
            logger.error("[%s] create_event network error: %s", self.client_id, e)
            return {"error": f"Google Calendar unreachable: {e}"}

    def cancel_event(self, event_id: str) -> dict:
        """Execute cancel event for GoogleCalendarIntegration."""
        return self._cancel_event(event_id)

    def _cancel_event(self, event_id: str) -> dict:
        """Execute cancel event for GoogleCalendarIntegration."""
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/calendars/primary/events/{event_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"cancelled": True, "event_id": event_id}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Google Calendar auth expired."}
            if e.response.status_code == 404:
                return {"error": f"Event '{event_id}' not found — it may already be cancelled."}
            return {"error": f"Cancel failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] cancel_event network error: %s", self.client_id, e)
            return {"error": f"Google Calendar unreachable: {e}"}
        
    def patch_attendees(self, event_id: str, new_emails: list) -> dict:
        """Add attendees to an existing event without rescheduling."""
        try:
            get_resp = httpx.get(
                f"{self.BASE_URL}/calendars/primary/events/{event_id}",
                headers=self.headers,
                timeout=10,
            )
            get_resp.raise_for_status()
            existing = get_resp.json()
            current_attendees = [a["email"] for a in existing.get("attendees", [])]
            merged = list({*current_attendees, *new_emails})

            patch_resp = httpx.patch(
                f"{self.BASE_URL}/calendars/primary/events/{event_id}",
                headers=self.headers,
                json={"attendees": [{"email": e} for e in merged], "sendUpdates": "all"},
                timeout=10,
            )
            patch_resp.raise_for_status()
            return {"updated": True, "event_id": event_id, "attendees": merged}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Google Calendar auth expired — please reconnect Google in integrations."}
            if e.response.status_code == 404:
                return {"error": f"Event '{event_id}' not found — it may have been deleted."}
            logger.error("[%s] patch_attendees failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Google Calendar error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] patch_attendees network error: %s", self.client_id, e)
            return {"error": f"Google Calendar unreachable: {e}"}