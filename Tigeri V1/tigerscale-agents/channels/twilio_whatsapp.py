"""Contain Twilio WhatsApp channel backend logic."""
import base64
import hashlib
import hmac
import json
import io

import httpx
import redis as redis_lib

from channels.base_channel import BaseChannel, Message
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

# Module-level Redis singleton — same pattern as channel_registry and webhook files.
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)


def validate_twilio_signature(
    auth_token: str, signature: str, url: str, params: dict
) -> bool:
    """Validate X-Twilio-Signature using HMAC-SHA1 per Twilio spec.

    Algorithm (https://www.twilio.com/docs/usage/webhooks/webhooks-security):
      1. Start with the full URL of the request.
      2. Append all POST parameters sorted alphabetically (key + value, no delimiter).
      3. Sign with HMAC-SHA1 using Auth Token as key.
      4. Base64-encode the digest and compare with X-Twilio-Signature header.
    """
    s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    computed = base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature)


class TwilioWhatsAppChannel(BaseChannel):

    """Represent the TwilioWhatsAppChannel component and its related behavior."""

    BASE_URL = "https://api.twilio.com"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)

        # Auth Token is stored as access_token via bootstrap_token convention.
        from integrations.token_manager import _get_stored
        stored = _get_stored(f"twilio_whatsapp:{client_id}") or {}
        self.auth_token = stored.get("access_token", "")

        # account_sid and from_number are stored in integration meta (not a secret).
        meta_raw = _redis.get(f"integration:meta:{client_id}:twilio_whatsapp")
        meta = json.loads(meta_raw) if meta_raw else {} # type: ignore
        self.account_sid = meta.get("account_sid", "")
        self.from_number = meta.get("from_number", "")

    def _check_configured(self) -> bool:
        """Check configured."""
        if not self.account_sid or not self.auth_token:
            self.log("Twilio WhatsApp not configured for this client", level="WARNING")
            return False
        return True

    def parse(self, payload: dict) -> Message:
        """Parse the requested operation.

        Twilio delivers form-encoded POST bodies. FastAPI form() parsing already
        converts them to a plain dict before this method is called.

        Incoming WhatsApp numbers use the format "whatsapp:+14155238886".
        We normalise the sender to a plain digit string to match the convention
        used by the 360dialog and Meta providers.
        """
        try:
            raw_from = payload.get("From", "")
            # Strip "whatsapp:+" prefix → plain digits ("14155238886")
            sender = raw_from.replace("whatsapp:", "").replace("+", "").strip()

            num_media = int(payload.get("NumMedia", "0") or 0)
            mime_type = ""
            filename = ""
            file_bytes = b""

            if num_media > 0:
                # Twilio provides MediaUrl0 / MediaContentType0 for the first attachment.
                media_url = payload.get("MediaUrl0", "")
                mime_type = payload.get("MediaContentType0", "")
                is_image = mime_type.startswith("image/")

                if is_image:
                    filename = "image.jpg"
                else:
                    ext = mime_type.split("/")[-1].split(";")[0].strip()
                    filename = f"file.{ext}" if ext else "document"

                content, file_bytes = self._fetch_file_content(
                    media_url=media_url,
                    mime_type=mime_type,
                    filename=filename,
                )
                caption = (payload.get("Body", "") or "").strip()
                if caption:
                    extracted = content.strip()
                    label = "[Image content]" if is_image else "[Document content]"
                    content = (
                        f"{caption}\n\n{label}\n{extracted[:4000]}"
                        if extracted else caption
                    )
                elif not content.strip():
                    content = (
                        "bill receipt document"
                        if is_image
                        else f"bill receipt document: {filename}"
                    )
            else:
                content = (payload.get("Body", "") or "").strip()
                if not content:
                    content = "[Unsupported message type]"

            return Message(
                client_id=self.client_id,
                sender=sender,
                content=content,
                channel="twilio_whatsapp",
                raw=payload,
                mime_type=mime_type,
                filename=filename,
                file_bytes=file_bytes,
            )
        except (KeyError, ValueError) as e:
            self.log(f"Failed to parse payload: {e}", level="ERROR")
            raise ValueError(f"Invalid Twilio WhatsApp payload: {e}")

    def send(self, recipient: str, message: str) -> bool:
        """Send the requested operation."""
        if not self._check_configured():
            return False

        # Ensure whatsapp:+ prefix for "To" and "From".
        to = (
            f"whatsapp:+{recipient}"
            if not recipient.startswith("whatsapp:")
            else recipient
        )
        frm = (
            f"whatsapp:+{self.from_number}"
            if not self.from_number.startswith("whatsapp:")
            else self.from_number
        )

        try:
            response = httpx.post(
                f"{self.BASE_URL}/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                auth=(self.account_sid, self.auth_token),
                data={"To": to, "From": frm, "Body": message},
                timeout=10,
            )
            if not response.is_success:
                self.log(
                    f"send failed: HTTP {response.status_code} | To={to} From={frm} | body={response.text}",
                    level="ERROR",
                )
                return False
            return True
        except httpx.HTTPError as e:
            self.log(f"send failed: {e}", level="ERROR")
            return False

    def send_document(
        self,
        recipient: str,
        document: bytes,
        filename: str,
        caption: str = "",
    ) -> bool:
        """Send a document via Twilio WhatsApp using a short-lived media URL.

        Twilio requires a publicly reachable URL for outbound media. We store
        the file in Redis for 5 minutes, expose it via /media/{token}, then
        pass that URL as MediaUrl to the Twilio Messages API.
        """
        if not self._check_configured():
            return False

        import secrets
        import base64
        import mimetypes
        import redis as _redis_bytes_lib

        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        token = secrets.token_urlsafe(32)
        # Store as "<mime>\n<base64data>" so the endpoint can reconstruct it.
        payload = mime.encode() + b"\n" + base64.b64encode(document)
        # Use a binary Redis client — decode_responses=True can't handle bytes.
        _rb = _redis_bytes_lib.from_url(settings.redis_url, decode_responses=False)
        _rb.setex(f"media:tmp:{token}", 300, payload)

        media_url = f"{settings.backend_url}/media/{token}"

        to = (
            f"whatsapp:+{recipient}"
            if not recipient.startswith("whatsapp:")
            else recipient
        )
        frm = (
            f"whatsapp:+{self.from_number}"
            if not self.from_number.startswith("whatsapp:")
            else self.from_number
        )

        try:
            data: dict = {"To": to, "From": frm, "MediaUrl": media_url}
            if caption:
                data["Body"] = caption
            response = httpx.post(
                f"{self.BASE_URL}/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                auth=(self.account_sid, self.auth_token),
                data=data,
                timeout=15,
            )
            if not response.is_success:
                self.log(
                    f"send_document failed: HTTP {response.status_code} | body={response.text}",
                    level="ERROR",
                )
                # Fallback — send text so user knows the doc was generated
                fallback = caption.strip() if caption.strip() else f"Document ready: {filename}"
                return self.send(recipient, fallback)
            return True
        except httpx.HTTPError as e:
            self.log(f"send_document failed: {e}", level="ERROR")
            fallback = caption.strip() if caption.strip() else f"Document ready: {filename}"
            return self.send(recipient, fallback)

    def _fetch_file_content(
        self, media_url: str, mime_type: str, filename: str
    ) -> tuple[str, bytes]:
        """Retrieve file content and raw bytes.

        Twilio media URLs require HTTP Basic Auth (Account SID + Auth Token).
        """
        from channels.file_processor import fetch_and_extract
        try:
            resp = httpx.get(
                media_url,
                auth=(self.account_sid, self.auth_token),
                timeout=30,
                follow_redirects=True,
            )
            resp.raise_for_status()
            content_type = (
                resp.headers.get("content-type", mime_type).split(";")[0].strip()
            )
            return fetch_and_extract(
                data=resp.content,
                mime_type=content_type,
                filename=filename,
            )
        except Exception as e:
            self.log(f"File fetch failed: {e}", level="ERROR")
            return f"[File could not be processed: {e}]", b""
