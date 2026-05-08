"""Contain email backend logic."""
import logging
import httpx
from channels.base_channel import BaseChannel, Message

logger = logging.getLogger(__name__)


class EmailChannel(BaseChannel):

    """Represent the EmailChannel component and its related behavior."""
    GRAPH_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        
    @property
    def _token(self) -> str:
        """Execute token for EmailChannel."""
        from integrations.token_manager import _get_valid_token
        return _get_valid_token("outlook", client_id=self.client_id)

    def parse(self, payload: dict) -> Message:
        """Parse the requested operation."""
        try:
            sender  = payload["from"]["emailAddress"]["address"]
            content = payload.get("body", {}).get("content", "")
            subject = payload.get("subject", "")
            return Message(
                client_id=self.client_id,
                sender=sender,
                content=f"Subject: {subject}\n\n{content}",
                channel="email",
                raw=payload,
            )
        except (KeyError, IndexError) as e:
            logger.error("EmailChannel parse failed client=%s: %s", self.client_id, e)
            raise ValueError(f"Invalid email payload: {e}")

    def send(
        self,
        recipient:       str,
        message:         str = "",
        subject:         str = "",
        body:            str = "",
        html:            str = "",
        attachment:      bytes = b"",
        attachment_name: str = "",
    ) -> bool:
        """Send the requested operation."""
        import base64

        if message and not subject:
            subject, body = self._split_message(message)

        subject = subject or "Message from Tigeri"
        content_type = "HTML" if html else "Text"
        content      = html  if html else body

        msg: dict = {
            "subject": subject,
            "body":    {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }

        if attachment and attachment_name:
            msg["attachments"] = [{
                "@odata.type":  "#microsoft.graph.fileAttachment",
                "name":         attachment_name,
                "contentType":  "application/pdf",
                "contentBytes": base64.b64encode(attachment).decode(),
            }]

        try:
            response = httpx.post(
                f"{self.GRAPH_URL}/me/sendMail",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type":  "application/json",
                },
                json={"message": msg},
                timeout=15,
            )
            response.raise_for_status()
            logger.info("Email sent client=%s to=%s", self.client_id, recipient)
            return True
        except httpx.HTTPError as e:
            logger.error("Email send failed client=%s to=%s: %s",
                         self.client_id, recipient, e)
            return False

    @staticmethod
    def _split_message(message: str) -> tuple[str, str]:
        """Execute split message for EmailChannel."""
        lines   = message.strip().split("\n")
        subject = lines[0] if lines else "Message from Tigeri"
        body    = "\n".join(lines[1:]).strip() if len(lines) > 1 else message
        return subject, body