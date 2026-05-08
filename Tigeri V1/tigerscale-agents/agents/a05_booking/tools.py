"""Contain tools backend logic."""
import json
from config.settings import settings
from core.prompts import BOOKING_TOOLS_PROMPT
from agents.base_agent import _get_client


def parse_booking_request(message: str) -> dict:
    """Parse booking request."""
    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=BOOKING_TOOLS_PROMPT,
        messages=[{"role": "user", "content": message}]
    )

    for block in response.content:
        if block.type == "text":
            try:
                return json.loads(block.text.strip())
            except json.JSONDecodeError:
                return {}

    return {}


def validate_booking(data: dict) -> tuple[bool, str]:
    """Validate booking."""
    from agents.a05_booking.config import BOOKING_CONFIG

    if not data.get("action"):
        return False, "Missing action"

    if data["action"] not in BOOKING_CONFIG["valid_actions"]:
        return False, f"Invalid action: {data['action']}"

    if data["action"] == "create_booking":
        if not data.get("date"):
            return False, "Missing date for booking"
        if not data.get("client_name"):
            return False, "Missing client name"

    return True, "ok"


def format_booking_confirmation(action: str, data: dict) -> str:
    """Execute format booking confirmation."""
    if action == "create_booking":
        return (
            f"Booking confirmed:\n"
            f"Client: {data.get('client_name')}\n"
            f"Date: {data.get('date')}\n"
            f"Time: {data.get('time', 'TBD')}\n"
            f"Duration: {data.get('duration_minutes', 60)} mins\n"
            f"Notes: {data.get('notes', 'N/A')}"
        )
    elif action == "cancel_booking":
        return f"Booking cancelled for {data.get('client_name')} on {data.get('date')}"

    elif action == "reschedule_booking":
        return f"Booking rescheduled for {data.get('client_name')} to {data.get('date')} at {data.get('time')}"

    elif action == "check_availability":
        return f"Checking availability for {data.get('date')}"

    return "Booking action completed."