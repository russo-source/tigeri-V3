"""Contain calendar factory backend logic."""
from typing import Protocol as _Protocol


class CalendarSystem(_Protocol):
    """Represent the CalendarSystem component and its related behavior."""
    # Check free/busy availability for a given time slot.
    def check_availability(self, date: str, time: str, duration_minutes: int) -> dict: ...
    # Create a calendar event with provider-specific payload data.
    def create_event(self, data: dict) -> dict: ...
    # Cancel an existing calendar event by its identifier.
    def cancel_event(self, event_id: str) -> dict: ...
    # Add attendees to an existing calendar event by its identifier.
    def patch_attendees(self, event_id: str, new_emails: list) -> dict: ...


def get_calendar_system(client_id: str, system: str) -> CalendarSystem:
    """Return calendar system."""
    normalized = system.lower().strip()
    if normalized in ("google", "google_calendar"):
        from integrations.google_calendar import GoogleCalendarIntegration
        return GoogleCalendarIntegration(client_id=client_id)
    elif normalized in ("outlook", "outlook_calendar", "microsoft", "ms365", "microsoft365"):
        from integrations.outlook_calendar import OutlookCalendarIntegration
        return OutlookCalendarIntegration(client_id=client_id)
    else:
        raise ValueError(
            "No calendar integration connected. "
            "Please connect Google Calendar or Outlook in integrations."
        )


def get_calendar_from_config(client_id: str) -> CalendarSystem:
    """Return calendar from config."""
    from integrations.integration_resolver import resolve_provider
    system = resolve_provider(client_id, "calendar")
    if not system:
        raise ValueError(
            "No calendar integration connected. "
            "Please connect Google Calendar or Outlook in integrations."
        )
    return get_calendar_system(client_id=client_id, system=system)