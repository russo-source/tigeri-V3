"""Contain gmail backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)


class GmailIntegration:

    """Represent the GmailIntegration component and its related behavior."""
    BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        from integrations.resilience import CircuitBreaker
        self._breaker = CircuitBreaker(f"gmail:{client_id}")

    @property
    def headers(self) -> dict:
        """Execute headers for GmailIntegration."""
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("google", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def send(
        self,
        recipient:str,
        subject:str,
        body:str,
        html:str = "",
        attachment:bytes = b"",
        attachment_name: str= "",
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
        import base64
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email import encoders

        msg = MIMEMultipart("mixed")
        msg["to"] = recipient
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        if html:
            msg.attach(MIMEText(html, "html"))
        if attachment and attachment_name:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            response = httpx.post(
                f"{self.BASE_URL}/messages/send",
                headers=self.headers,
                json={"raw": raw},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("[%s] Gmail auth expired", self.client_id)
                raise
            logger.error("[%s] Gmail send failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            raise
        except httpx.HTTPError as e:
            logger.error("[%s] Gmail network error: %s", self.client_id, e)
            raise

    def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """List messages."""
        return self._breaker.call(self._list_messages, query, max_results)
    
    def _list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """List messages."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/messages",
                headers=self.headers,
                params={"q": query, "maxResults": max_results},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("messages", [])
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
                params={"format": "full"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("[%s] get_message failed: %s", self.client_id, e)
            return {}