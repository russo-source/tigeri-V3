"""Contain telegram backend logic."""
import io
import re
import httpx
from channels.base_channel import BaseChannel, Message
from config.settings import settings
import logging

logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    """Execute escape md."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)


class TelegramChannel(BaseChannel):

    """Represent the TelegramChannel component and its related behavior."""
    BASE_URL = "https://api.telegram.org"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        from integrations.token_manager import _get_stored
        stored = _get_stored(f"telegram:{client_id}") or {}
        self.token = stored.get("access_token", "")
        self.api_url = f"{self.BASE_URL}/bot{self.token}" if self.token else None
    def _check_configured(self) -> bool:
        """Check configured."""
        if not self.token or not self.api_url:
            self.log("telegram not configured for this client", level="WARNING")
            return False
        return True

    def parse(self, payload: dict) -> Message:
        """Parse the requested operation."""
        try:
            message = payload["message"]
            sender = str(message["from"]["id"])
            mime_type = ""
            filename = ""
            file_bytes = b""

            if "text" in message:
                content = message["text"]

            elif "document" in message:
                doc = message["document"]
                mime_type = doc.get("mime_type", "")
                filename = doc.get("file_name", "")
                content, file_bytes = self._fetch_file_content(
                    file_id=doc["file_id"],
                    mime_type=mime_type,
                    filename=filename,
                )
                caption = message.get("caption", "")
                if caption:
                    extracted = content.strip()
                    content = (
                        f"{caption}\n\n[Document content]\n{extracted[:4000]}"
                        if extracted else caption
                    )
                elif not content.strip():
                    content = f"bill receipt document: {filename or 'file'}"

            elif "photo" in message:
                photo = message["photo"][-1]
                mime_type = "image/jpeg"
                filename = "photo.jpg"
                content, file_bytes = self._fetch_file_content(
                    file_id=photo["file_id"],
                    mime_type=mime_type,
                    filename=filename,
                )
                caption = message.get("caption", "")
                if caption:
                    extracted = content.strip()
                    content = (
                        f"{caption}\n\n[Image content]\n{extracted[:4000]}"
                        if extracted else caption
                    )
                elif not content.strip():
                    content = "bill receipt document"

            else:
                content = "[Unsupported message type]"

            return Message(
                client_id=self.client_id,
                sender=sender,
                content=content,
                channel="telegram",
                raw=payload,
                mime_type=mime_type,
                filename=filename,
                file_bytes=file_bytes,
            )
        except (KeyError, IndexError) as e:
            self.log(f"Failed to parse payload: {e}", level="ERROR")
            raise ValueError(f"Invalid Telegram payload: {e}")

    def send(self, recipient: str, message: str) -> bool:
        if not self._check_configured():
            return False
        try:
            response = httpx.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": recipient,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            self.log(f"send failed {e.response.status_code}: {e.response.text}", level="ERROR")
            return False
        except httpx.HTTPError as e:
            self.log(f"send failed: {e}", level="ERROR")
            return False

    def send_with_buttons(self, recipient: str, message: str, buttons: list[dict]) -> bool:
        if not self._check_configured():
            return False
        try:
            response = httpx.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": recipient,
                    "text": message,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": b["label"], "callback_data": b["data"]}
                             for b in buttons]
                        ]
                    },
                },
                timeout=10,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            self.log(f"send_with_buttons failed {e.response.status_code}: {e.response.text}", level="ERROR")
            return False
        except httpx.HTTPError as e:
            self.log(f"send_with_buttons failed: {e}", level="ERROR")
            return False

    def send_document(self, recipient: str, document: bytes, filename: str, caption: str = "") -> bool:
        if not self._check_configured():
            return False
        try:
            response = httpx.post(
                f"{self.api_url}/sendDocument",
                data={
                    "chat_id": recipient,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"document": (filename, io.BytesIO(document), "application/pdf")},
                timeout=30,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            self.log(f"send_document failed {e.response.status_code}: {e.response.text}", level="ERROR")
            return False
        except httpx.HTTPError as e:
            self.log(f"send_document failed: {e}", level="ERROR")
            return False

    def _fetch_file_content(self, file_id: str, mime_type: str, filename: str) -> tuple[str, bytes]:
        """Retrieve file content and raw bytes."""
        from channels.file_processor import fetch_and_extract
        try:
            resp = httpx.get(
                f"{self.api_url}/getFile",
                params={"file_id": file_id},
                timeout=10,
            )
            resp.raise_for_status()
            file_path = resp.json()["result"]["file_path"]
            download_url = f"{self.BASE_URL}/file/bot{self.token}/{file_path}"
            return fetch_and_extract(
                url=download_url,
                headers={},
                mime_type=mime_type,
                filename=filename,
            )
        except Exception as e:
            self.log(f"File fetch failed: {e}", level="ERROR")
            return f"[File could not be processed: {e}]", b""