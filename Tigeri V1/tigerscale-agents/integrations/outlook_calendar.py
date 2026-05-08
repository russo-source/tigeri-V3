"""Contain outlook calendar backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)


class OutlookCalendarIntegration:

    """Represent the OutlookCalendarIntegration component and its related behavior."""
    BASE_URL = "https://graph.microsoft.com/v1.0/me"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id

    @property
    def headers(self) -> dict:
        """Execute headers for OutlookCalendarIntegration."""
        from integrations.token_manager import _get_valid_token
        token = _get_valid_token("outlook", client_id=self.client_id)
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

            response = httpx.get(
                f"{self.BASE_URL}/calendarView",
                headers=self.headers,
                params={
                    "startDateTime": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateTime": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "$select": "subject,start,end",
                },
                timeout=10,
            )
            response.raise_for_status()
            events = response.json().get("value", [])
            return {"available": len(events) == 0, "conflicts": [e.get("subject") for e in events]}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Microsoft 365 auth expired - please reconnect Outlook in integrations."}
            logger.error("[%s] check_availability failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Outlook Calendar error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] check_availability network error: %s", self.client_id, e)
            return {"error": f"Outlook Calendar unreachable: {e}"}
        except Exception as e:
            logger.error("[%s] check_availability unexpected error: %s", self.client_id, e)
            return {"error": f"Outlook availability check failed - {e}"}

    def create_event(self, data: dict) -> dict:
        """Create event."""
        return self._create_event(data)

    def _create_event(self, data: dict) -> dict:
        """Create event."""
        timezone = data.get("timezone", "UTC")
        payload = {
            "subject": data.get("subject", "Meeting"),
            "body": {"contentType": "Text", "content": data.get("description", "")},
            "start": {"dateTime": data.get("start"), "timeZone": timezone},
            "end": {"dateTime": data.get("end"), "timeZone": timezone},
            "attendees": [
                {"emailAddress": {"address": a}, "type": "required"}
                for a in data.get("attendees", []) if a
            ],
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
        }
        try:
            response = httpx.post(
                f"{self.BASE_URL}/events",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            if not result:
                return {"error": "Empty response from Outlook Calendar."}

            online_meeting = result.get("onlineMeeting") or {}
            teams_link = online_meeting.get("joinUrl", "")
            web_link = result.get("webLink", "")
            start_block = result.get("start") or {}
            end_block = result.get("end") or {}
            attendees = [
                (a.get("emailAddress") or {}).get("address")
                for a in (result.get("attendees") or [])
            ]
            return {
                "event_id": result.get("id", ""),
                "title": result.get("subject", ""),
                "start": start_block.get("dateTime", data.get("start", "")),
                "end": end_block.get("dateTime", data.get("end", "")),
                "link": teams_link or web_link,
                "teams_link": teams_link,
                "attendees": attendees,
                "provider": "outlook",
                "timezone": timezone,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Microsoft 365 auth expired - please reconnect Outlook in integrations."}
            logger.error("[%s] create_event failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Outlook Calendar error: {e.response.status_code} - {e.response.text}"}
        except httpx.HTTPError as e:
            logger.error("[%s] create_event network error: %s", self.client_id, e)
            return {"error": f"Outlook Calendar unreachable: {e}"}
        except Exception as e:
            logger.error("[%s] create_event unexpected error: %s", self.client_id, e)
            return {"error": f"Outlook event creation failed - {e}"}

    def cancel_event(self, event_id: str) -> dict:
        """Execute cancel event for OutlookCalendarIntegration."""
        return self._cancel_event(event_id)

    def _cancel_event(self, event_id: str) -> dict:
        """Execute cancel event for OutlookCalendarIntegration."""
        if not event_id:
            return {"error": "No event ID provided - cannot cancel."}
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/events/{event_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"cancelled": True, "event_id": event_id}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Microsoft 365 auth expired - please reconnect Outlook in integrations."}
            if e.response.status_code == 404:
                return {"error": f"Event '{event_id}' not found - it may already be cancelled."}
            return {"error": f"Cancel failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] cancel_event network error: %s", self.client_id, e)
            return {"error": f"Outlook Calendar unreachable: {e}"}
        
    def patch_attendees(self, event_id: str, new_emails: list) -> dict:
        """Add attendees to an existing event without rescheduling."""
        try:
            get_resp = httpx.get(
                f"{self.BASE_URL}/events/{event_id}",
                headers=self.headers,
                params={"$select": "id,subject,attendees"},
                timeout=10,
            )
            get_resp.raise_for_status()
            existing = get_resp.json()
            current_attendees = [
                (a.get("emailAddress") or {}).get("address")
                for a in existing.get("attendees", [])
            ]
            current_attendees = [e for e in current_attendees if e]
            merged = list({*current_attendees, *new_emails})

            patch_resp = httpx.patch(
                f"{self.BASE_URL}/events/{event_id}",
                headers=self.headers,
                json={
                    "attendees": [
                        {"emailAddress": {"address": e}, "type": "required"}
                        for e in merged
                    ]
                },
                timeout=10,
            )
            patch_resp.raise_for_status()
            return {"updated": True, "event_id": event_id, "attendees": merged}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Microsoft 365 auth expired — please reconnect Outlook in integrations."}
            if e.response.status_code == 404:
                return {"error": f"Event '{event_id}' not found — it may have been deleted."}
            logger.error("[%s] patch_attendees failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Outlook Calendar error: {e.response.status_code} — {e.response.text}"}
        except httpx.HTTPError as e:
            logger.error("[%s] patch_attendees network error: %s", self.client_id, e)
            return {"error": f"Outlook Calendar unreachable: {e}"}
        except Exception as e:
            logger.error("[%s] patch_attendees unexpected error: %s", self.client_id, e)
            return {"error": f"Outlook patch attendees failed — {e}"}