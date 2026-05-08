"""Contain whatsapp backend logic."""
import io
import httpx
from channels.base_channel import BaseChannel, Message
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

class WhatsAppChannel(BaseChannel):

    """Represent the WhatsAppChannel component and its related behavior."""
    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        from integrations.token_manager import _get_stored
        stored = _get_stored(f"whatsapp:{client_id}") or {}
        self.api_key = stored.get("access_token", "")

    @property
    def BASE_URL(self) -> str:
        """Execute BASE URL for WhatsAppChannel."""
        return (
            "https://waba-sandbox.360dialog.io/v1"
            if settings.env == "development"
            else "https://waba.360dialog.io/v1"
        )

    def parse(self, payload: dict) -> Message:
        """Parse the requested operation."""
        try:
            contact = payload["contacts"][0]
            msg = payload["messages"][0]
            sender = contact.get("wa_id", "unknown")
            msg_type = msg.get("type", "text")
            mime_type = ""
            filename = ""
            file_bytes = b""

            if msg_type == "text":
                content = msg.get("text", {}).get("body", "")

            elif msg_type == "document":
                doc = msg["document"]
                mime_type = doc.get("mime_type", "")
                filename = doc.get("filename", "")
                content, file_bytes = self._fetch_file_content(
                    file_id=doc.get("id", ""),
                    mime_type=mime_type,
                    filename=filename,
                    direct_url=doc.get("url", ""),
                )
                caption = doc.get("caption", "") or msg.get("caption", "")
                if caption:
                    extracted = content.strip()
                    content = (
                        f"{caption}\n\n[Document content]\n{extracted[:4000]}"
                        if extracted else caption
                    )
                elif not content.strip():
                    content = f"bill receipt document: {filename or 'file'}"

            elif msg_type == "image":
                img = msg["image"]
                mime_type = img.get("mime_type", "image/jpeg")
                filename = "image.jpg"
                content, file_bytes = self._fetch_file_content(
                    file_id=img.get("id", ""),
                    mime_type=mime_type,
                    filename=filename,
                    direct_url=img.get("url", ""),
                )
                caption = img.get("caption", "") or msg.get("caption", "")
                if caption:
                    extracted = content.strip()
                    content = (
                        f"{caption}\n\n[Image content]\n{extracted[:4000]}"
                        if extracted else caption
                    )
                elif not content.strip():
                    content = "bill receipt document"

            else:
                content = f"[Unsupported message type: {msg_type}]"

            return Message(
                client_id=self.client_id,
                sender=sender,
                content=content,
                channel="whatsapp",
                raw=payload,
                mime_type=mime_type,
                filename=filename,
                file_bytes=file_bytes,
            )
        except (KeyError, IndexError) as e:
            self.log(f"Failed to parse payload: {e}", level="ERROR")
            raise ValueError(f"Invalid WhatsApp payload: {e}")

    def send(self, recipient: str, message: str) -> bool:
        """Send the requested operation."""
        if not self.api_key:
            self.log("WhatsApp not configured for this client", level="WARNING")
            return False
        try:
            response = httpx.post(
                f"{self.BASE_URL}/messages",
                headers={"D360-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient,
                    "type": "text",
                    "text": {"body": message},
                },
                timeout=10,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            self.log(f"send failed: {e}", level="ERROR")
            return False

    def send_document(self, recipient: str, document: bytes, filename: str, caption: str = "") -> bool:
        """Send document."""
        if not self.api_key:
            self.log("WhatsApp not configured for this client", level="WARNING")
            return False
        try:
            upload = httpx.post(
                f"{self.BASE_URL}/media",
                headers={"D360-API-KEY": self.api_key},
                files={"file": (filename, io.BytesIO(document), "application/pdf")},
                data={"messaging_product": "whatsapp"},
                timeout=30,
            )
            upload.raise_for_status()
            media_id = upload.json().get("media", [{}])[0].get("id")
            if not media_id:
                raise ValueError(f"No media ID in upload response: {upload.text}")

            send = httpx.post(
                f"{self.BASE_URL}/messages",
                headers={"D360-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient,
                    "type": "document",
                    "document": {"id": media_id, "filename": filename, "caption": caption},
                },
                timeout=15,
            )
            send.raise_for_status()
            return True

        except (httpx.HTTPError, ValueError) as e:
            self.log(f"send_document failed: {e}", level="ERROR")
            return False

    def _fetch_file_content(self, file_id: str, mime_type: str, filename: str, direct_url: str = "") -> tuple[str, bytes]:
        """Retrieve file content and raw bytes."""
        from channels.file_processor import fetch_and_extract
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/media/{file_id}",
                headers={"D360-API-KEY": self.api_key},
                timeout=15,
                follow_redirects=True,
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", mime_type).split(";")[0].strip()
            return fetch_and_extract(
                data=resp.content,
                mime_type=content_type,
                filename=filename,
            )
        except Exception as e:
            self.log(f"File fetch failed: {e}", level="ERROR")
            return f"[File could not be processed: {e}]", b""