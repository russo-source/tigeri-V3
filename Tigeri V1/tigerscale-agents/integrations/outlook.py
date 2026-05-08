"""Contain outlook backend logic."""
import base64
import logging
import httpx

logger = logging.getLogger(__name__)
from integrations.resilience import CircuitBreaker


class OutlookIntegration:

    """Represent the OutlookIntegration component and its related behavior."""
    BASE_URL = "https://graph.microsoft.com/v1.0/me"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"outlook:{client_id}")

    @property
    def headers(self) -> dict:
        """Execute headers for OutlookIntegration."""
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("outlook", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        html: str = "",
        attachment: bytes = b"",
        attachment_name: str = "",
    ) -> bool:
        """Send the requested operation."""
        return self._breaker.call(
            self._send, recipient, subject, body, html, attachment, attachment_name
        )

    def _send(
        self,
        recipient: str,
        subject: str,
        body: str,
        html: str = "",
        attachment: bytes = b"",
        attachment_name: str = "",
    ) -> bool:
        """Send the requested operation."""
        content_type = "HTML" if html else "Text"
        content = html if html else body

        message: dict = {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if attachment and attachment_name:
            message["attachments"] = [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment_name,
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(attachment).decode(),
            }]

        try:
            response = httpx.post(
                f"{self.BASE_URL}/sendMail",
                headers=self.headers,
                json={"message": message},
                timeout=15,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("[%s] Outlook auth expired", self.client_id)
                raise
            logger.error("[%s] Outlook send failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            raise
        except httpx.HTTPError as e:
            logger.error("[%s] Outlook send network error: %s", self.client_id, e)
            raise

    def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """List messages."""
        return self._breaker.call(self._list_messages, query, max_results)

    def _list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """List messages."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/mailFolders/inbox/messages",
                headers=self.headers,
                params={"$top": max_results, "$orderby": "receivedDateTime desc", "$search": f'"{query}"' if query else None},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPError as e:
            logger.error("[%s] list_messages failed: %s", self.client_id, e)
            return []

    def get_message(self, message_id: str) -> dict:
        """Return message."""
        return self._breaker.call(self._get_message, message_id)

    def _get_message(self, message_id: str) -> dict:
        """Return message."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/messages/{message_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("[%s] get_message failed: %s", self.client_id, e)
            return {}