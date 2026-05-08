"""Contain document router backend logic."""
from dataclasses import dataclass
from channels.base_channel import Message


# Constant for inbound mime types.
INBOUND_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Constant for inbound extensions.
INBOUND_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".docx"}

_DOC_MARKERS = [
    "invoice no", "invoice #", "inv-", "bill to", "billed to",
    "amount due", "balance due", "grand total", "payment due",
    "subtotal", "tax invoice", "purchase order", "po number",
    "remit to", "due date", "net 30", "net 60",
]
_ADMIN_CAPTION_KEYWORDS = (
    "save", "upload", "store", "put in", "file this", "add to",
    "add this", "move to", "folder", "drive", "contracts", "invoices",
    "documents", "read", "open", "summarize", "summarise", "what does",
    "extract", "translate", "analyze", "analyse",
)


@dataclass
class RoutedMessage:
    """Represent the RoutedMessage component and its related behavior."""
    message: Message
    route: str
    is_document: bool
    is_admin: bool
    filename: str
    mime_type: str


def route(message: Message, mime_type: str = "", filename: str = "") -> RoutedMessage:
    """Execute route."""
    is_document = _is_document(message.content, mime_type, filename)
    is_admin = is_document and _is_admin_intent(message.content, mime_type)
    route_name = "admin" if is_admin else ("inbound_bill" if is_document else "outbound_invoice")
    return RoutedMessage(
        message=message,
        route=route_name,
        is_document=is_document,
        is_admin=is_admin,
        filename=filename,
        mime_type=mime_type,
    )


def _is_document(content: str, mime_type: str, filename: str) -> bool:
    """Check whether document."""
    if mime_type and mime_type.lower() in INBOUND_MIME_TYPES:
        return True
    if filename:
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if ext in INBOUND_EXTENSIONS:
            return True
    if content and content.startswith("[File could not be processed"):
        return False
    if content and _looks_like_document(content):
        return True
    return False


def _is_admin_intent(content: str, mime_type: str) -> bool:
    """Return True if the file+caption signals admin storage/read intent, not a bill."""
    if content:
        lower = content.lower()
        if any(kw in lower for kw in _ADMIN_CAPTION_KEYWORDS):
            return True
    return False


def _looks_like_document(content: str) -> bool:
    """Execute looks like document."""
    lower = content.lower()
    hits  = sum(1 for m in _DOC_MARKERS if m in lower)
    return hits >= 3