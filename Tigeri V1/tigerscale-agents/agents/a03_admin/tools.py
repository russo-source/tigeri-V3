"""Contain tools backend logic."""
from __future__ import annotations
import json
import logging
import re
from datetime import date, datetime, timedelta
from agents.a03_admin.prompts import _ADMIN_CONFIRMATION_PROMPT, get_admin_tools_prompt
from agents.base_agent import _get_client

logger = logging.getLogger(__name__)

TIMEZONE_MAP: dict[str,str] = {
    "IST": "Asia/Kolkata", "EST": "America/New_York", "EDT": "America/New_York",
    "CST": "America/Chicago", "CDT": "America/Chicago", "MST": "America/Denver",
    "MDT": "America/Denver", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "GMT": "UTC", "UTC": "UTC", "BST": "Europe/London", "CET": "Europe/Paris",
    "CEST": "Europe/Paris", "JST": "Asia/Tokyo", "CST_CN": "Asia/Shanghai",
    "SGT": "Asia/Singapore", "AEST": "Australia/Sydney", "GST": "Asia/Dubai",
    "PKT": "Asia/Karachi", "BDT": "Asia/Dhaka",
}

COUNTRY_TIMEZONE_MAP: dict[str,str] = {
    "india": "Asia/Kolkata", "us": "America/New_York", "usa": "America/New_York",
    "uk": "Europe/London", "japan": "Asia/Tokyo", "china": "Asia/Shanghai",
    "singapore": "Asia/Singapore", "australia": "Australia/Sydney",
    "uae": "Asia/Dubai", "dubai": "Asia/Dubai", "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka", "germany": "Europe/Berlin",
    "france": "Europe/Paris", "canada": "America/Toronto",
}

def format_admin_confirmation_llm(action: str, data: dict, result: dict) -> str:
    """Build a natural-language confirmation for an admin action result."""
    result = result or {}
    facts: dict = {"action": action, "entity": data.get("entity_name") or "unknown"}

    if action == "file_document":
        facts.update({
            "document_type": data.get("document_type"),
            "filename": result.get("filename"),
            "folder": result.get("folder"),
            "error": result.get("error"),
        })

    elif action == "find_document":
        files = result.get("files", [])
        facts.update({
            "count": result.get("count", len(files)),
            "query": result.get("query", ""),
            "error": result.get("error"),
            "files": [
                {
                    "name": f.get("name") or f.get("title") or "",
                    "link": f.get("link") or f.get("webViewLink") or f.get("webUrl") or "",
                }
                for f in files[:5]
            ],
        })

    elif action == "list_documents":
        docs = result.get("documents", [])
        facts.update({
            "total": result.get("total", 0),
            "source": result.get("source", ""),
            "folder": result.get("folder", "root"),
            "error": result.get("error"),
            "documents": [
                {
                    "name": d.get("name") or d.get("filename") or "",
                    "link": d.get("link") or "",
                    "type": d.get("mime_type") or d.get("type") or "",
                }
                for d in docs[:8]
            ],
        })

    elif action == "send_communication":
        facts.update({
            "recipient": data.get("recipient_email"),
            "sent": result.get("sent", False),
            "error": result.get("error"),
        })

    elif action == "track_permit":
        facts.update({
            "document_type": data.get("document_type"),
            "expiry": data.get("expiry_date"),
            "days_left": result.get("days_left"),
            "found": result.get("found", False),
            "error": result.get("error"),
        })
    elif action == "schedule_meeting":
        if result.get("unavailable"):
            facts.update({
                "unavailable": True,
                "suggested_slots": result.get("suggested_slots", []),
                "conflicts": [
                    c.get("start", str(c)) if isinstance(c, dict) else str(c)
                    for c in result.get("conflicts", [])[:3]
                ],
            })
        else:
            event = result.get("event", {})
            facts.update({
                "scheduled": result.get("scheduled", False),
                "title": event.get("title"),
                "start": event.get("start"),
                "timezone": result.get("timezone", "UTC"),
                "link": event.get("link", ""),
                "attendees": event.get("attendees", []),
                "duration_minutes": data.get("meeting_duration", 60),
                "error": result.get("error"),
            })
    elif action == "add_attendee":
        facts.update({
            "updated": result.get("updated", False),
            "event_id": result.get("event_id"),
            "attendees": result.get("attendees", []),
            "error": result.get("error"),
        })
    elif action == "upload_document":
        facts.update({
            "uploaded": result.get("uploaded", False),
            "filename": result.get("filename"),
            "link": result.get("link", ""),
            "folder": result.get("folder", ""),
            "error": result.get("error"),
        })
    elif action == "read_document":
        facts.update({
            "read": result.get("read", False),
            "filename": result.get("filename"),
            "summary": (result.get("summary") or "")[:300],
            "error": result.get("error"),
        })
    elif action == "move_document":
        facts.update({
            "filename":    result.get("filename"),
            "from_folder": result.get("from_folder"),
            "to_folder":   result.get("to_folder"),
            "error":       result.get("error"),
        })
    elif action == "delete_document":
        facts.update({
            "filename": result.get("filename"),
            "deleted":  result.get("deleted", False),
            "error":    result.get("error"),
        })
    elif action == "rename_document":
        facts.update({
            "old_name": result.get("old_name"),
            "new_name": result.get("new_name"),
            "error":    result.get("error"),
        })
    elif action == "copy_document":
        facts.update({
            "filename":  result.get("filename"),
            "to_folder": result.get("to_folder"),
            "error":     result.get("error"),
        })
    elif action == "delete_folder":
        facts.update({
            "folder":  result.get("folder"),
            "deleted": result.get("deleted", False),
            "error":   result.get("error"),
        })
    elif action == "rename_folder":
        facts.update({
            "old_name": result.get("old_name"),
            "new_name": result.get("new_name"),
            "error":    result.get("error"),
        })
    elif action == "share_document":
        facts.update({
            "filename": result.get("filename"),
            "link":     result.get("link", ""),
            "error":    result.get("error"),
        })
    elif action == "get_document_info":
        facts.update({
            "name":     result.get("name"),
            "size":     result.get("size"),
            "mime":     result.get("mime"),
            "created":  result.get("created"),
            "modified": result.get("modified"),
            "link":     result.get("link"),
            "error":    result.get("error"),
        })
    elif action == "list_meetings":
        facts.update({
            "total": result.get("total", 0),
            "meetings": result.get("meetings", [])[:5],
            "error": result.get("error"),
        })
    elif action == "meeting_reminder":
        facts.update({
            "reminder_sent": result.get("reminder_sent", False),
            "sent_to": result.get("sent_to", []),
            "failed": result.get("failed", []),
            "error": result.get("error"),
        })

    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=_ADMIN_CONFIRMATION_PROMPT,
            messages=[{"role": "user", "content": f"Action completed: {json.dumps(facts, default=str)}"}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception as e:
        logger.warning("format_admin_confirmation_llm failed, using fallback: %s", e)

    return f"Admin {action} completed for {facts['entity']}."

def resolve_client_timezone(client_id: str) -> str:
    """Resolve client timezone."""
    try:
        from core.conversation import get_client_timezone
        tz = get_client_timezone(client_id)
        if tz:
            return tz
    except Exception:
        pass

    try:
        from config.client_config import get_client_financial_config
        fc = get_client_financial_config(client_id)
        tz = fc.get("timezone", "")
        if not tz and fc.get("country"):
            tz = COUNTRY_TIMEZONE_MAP.get(fc["country"].lower(), "")
        if tz:
            return tz
    except Exception:
        pass
    return "Asia/Kolkata"


def extract_timezone_from_message(message: str) -> str:
    """Execute extract timezone from message."""
    message_upper = message.upper()
    for abbr, tz_name in TIMEZONE_MAP.items():
        if re.search(rf"\b{abbr}\b", message_upper):
            return tz_name
    message_lower = message.lower()
    for keyword, tz_name in COUNTRY_TIMEZONE_MAP.items():
        if keyword in message_lower:
            return tz_name
    return ""


def get_effective_timezone(client_id: str, message: str) -> str:
    """Return effective timezone."""
    message_tz = extract_timezone_from_message(message)
    return message_tz if message_tz else resolve_client_timezone(client_id)

def _normalize_time(time_str: str) -> str:
    """Execute normalize time."""
    if not time_str:
        return time_str
    time_str = time_str.strip().lower()
    time_str = re.sub(
        r"\s*(ist|utc|gmt|est|pst|cst|bst|cet|jst|sgt|gst|pkt|bdt|aest|edt|cdt|mdt|pdt)\s*$",
        "", time_str,
    ).strip()
    time_str = time_str.replace(".", ":")
    if re.match(r"^\d{1,2}:\d{2}$", time_str):
        h, m = time_str.split(":")
        return f"{int(h):02d}:{m}"
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", time_str)
    if match:
        h = int(match.group(1))
        m = int(match.group(2) or 0)
        period = match.group(3)
        if period == "pm" and h != 12:
            h += 12
        elif period == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    if time_str == "noon":
        return "12:00"
    if time_str == "midnight":
        return "00:00"
    return time_str


def _normalize_date(date_str: str) -> str:
    """Execute normalize date."""
    if not date_str:
        return date_str
    date_str = date_str.strip()
    current_year = datetime.now().year
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        if parsed.year < current_year:
            date_str = date_str.replace(str(parsed.year), str(current_year), 1)
        return date_str
    if date_str.lower() == "tomorrow":
        return (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    if date_str.lower() == "today":
        return date.today().strftime("%Y-%m-%d")
    next_match = re.match(r"^next\s+(\w+)$", date_str.lower())
    if next_match:
        day_name = next_match.group(1)
        days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,"friday": 4, "saturday": 5, "sunday": 6,}
        if day_name in days:
            today = date.today()
            diff = (days[day_name] - today.weekday() + 7) % 7
            diff = diff if diff > 0 else 7
            return (today + timedelta(days=diff)).strftime("%Y-%m-%d")
    formats_with_year = [
        "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%d %b %Y",
        "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y",
        "%d-%b-%Y", "%d-%B-%Y", "%Y/%m/%d",
    ]
    formats_without_year = [
        "%d %B", "%d %b", "%B %d", "%b %d",
        "%d-%m", "%d/%m", "%d-%b", "%d-%B",
    ]
    for fmt in formats_with_year:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year < current_year:
                parsed = parsed.replace(year=current_year)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in formats_without_year:
        try:
            parsed = datetime.strptime(date_str, fmt)
            result = parsed.replace(year=current_year)
            if result.date() < date.today():
                result = result.replace(year=current_year + 1)
            return result.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def _extract_suggested_slot(message: str) -> dict:
    """Extract a pre-formatted suggested slot from a user reply."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s+at\s+(\d{2}:\d{2})\s*\(([^)]+)\)", message)
    if match:
        return {
            "action": "schedule_meeting",
            "meeting_date": match.group(1),
            "meeting_time": match.group(2),
            "timezone": match.group(3).strip(),
            "confidence": 0.95,
        }
    return {}


def parse_admin_request(message: str) -> dict:
    """
    Parse a natural-language admin request into a structured dict.
    """
    pre_parsed = _extract_suggested_slot(message)
    system_prompt = get_admin_tools_prompt()

    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()
            try:
                data = json.loads(text)
                if data.get("meeting_date"):
                    data["meeting_date"] = _normalize_date(data["meeting_date"])
                if data.get("meeting_time"):
                    data["meeting_time"] = _normalize_time(data["meeting_time"])
                if data.get("folder_name"):
                    fn = data["folder_name"].strip().lower().removesuffix(" folder").strip()
                    data["folder_name"] = fn if fn else None
                if pre_parsed:
                    data["action"] = data.get("action") or pre_parsed["action"]
                    data["meeting_date"] = pre_parsed["meeting_date"]
                    data["meeting_time"] = pre_parsed["meeting_time"]
                    data["timezone"] = pre_parsed["timezone"]
                    data.setdefault("confidence", pre_parsed["confidence"])
                return data
            except json.JSONDecodeError:
                return pre_parsed if pre_parsed else {}

    return pre_parsed if pre_parsed else {}


def validate_admin_request(data: dict) -> tuple[bool, str]:
    """Validate admin request."""
    from agents.a03_admin.config import ADMIN_CONFIG

    if not data.get("action"):
        return False, ( "Could not determine the action. "
            "Try: file a document, find a document, send a message, "
            "track a permit, or schedule a meeting."
        )

    if data["action"] not in ADMIN_CONFIG["valid_actions"]:
        return False, f"Unknown action: {data['action']}"

    if data["action"] == "schedule_meeting":
        if not data.get("meeting_date"):
            return False, "Please provide a date for the meeting."
        if not data.get("meeting_time"):
            return False, "Please provide a time for the meeting."
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", data["meeting_date"]):
            return False, (
                f"Could not parse date '{data['meeting_date']}' — "
                "use a format like '26 April' or '26-04-2026'."
            )
        if not re.match(r"^\d{2}:\d{2}$", data["meeting_time"]):
            return False, (
                f"Could not parse time '{data['meeting_time']}' — "
                "use a format like '11am' or '3:30pm'."
            )
        try:
            if datetime.strptime(data["meeting_date"], "%Y-%m-%d").date() < date.today():
                return False, (
                    f"Meeting date {data['meeting_date']} is in the past. "
                    "Please provide a future date."
                )
        except ValueError:
            pass

    if data["action"] == "send_communication":
        if not data.get("recipient_email"):
            return False, "Please provide the recipient's email address."
        if not data.get("content"):
            return False, "Please provide the message content."

    if data["action"] == "track_permit":
        if not data.get("entity_name") and not data.get("document_type"):
            return False, "Please provide the permit or entity name to track."

    if data["action"] == "add_attendee":
        if not data.get("attendees"):
            return False, "Please provide the email address of the attendee to add."

    return True, "ok"


def get_storage_integration(client_id: str, storage: str | None = None):
    """Return storage integration."""
    if storage is None:
        from integrations.integration_resolver import resolve_storage_provider
        storage = resolve_storage_provider(client_id)

    normalized = (storage or "").lower().strip()

    if normalized in ("google_drive", "google"):
        from integrations.google_drive import GoogleDriveIntegration
        return GoogleDriveIntegration(client_id=client_id)
    if normalized in ("sharepoint", "microsoft", "ms365"):
        from integrations.sharepoint import SharePointIntegration
        return SharePointIntegration(client_id=client_id)
    if normalized in ("onedrive", "one_drive", "outlook"):
        from integrations.onedrive import OneDriveIntegration
        return OneDriveIntegration(client_id=client_id)
    raise ValueError(
        f"No storage integration connected (resolved: '{storage}'). "
        "Please connect Google Drive, OneDrive, or SharePoint in Settings → Integrations."
    )