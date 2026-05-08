"""Contain email factory backend logic."""
from typing import Protocol as _Protocol2


class EmailSystem(_Protocol2):
    """Represent the EmailSystem component and its related behavior."""
    # Send an email message with optional HTML body and attachment.
    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        html: str = "",
        attachment: bytes = b"",
        attachment_name: str = "",
    ) -> bool: ...
    def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]: ...
    def get_message(self, message_id: str) -> dict: ...
    


def get_email_system(client_id: str, system: str) -> EmailSystem:
    """Return email system."""
    if system in ("google", "gmail"):
        from integrations.gmail import GmailIntegration
        return GmailIntegration(client_id=client_id)
    elif system in ("outlook",):
        from integrations.outlook import OutlookIntegration
        return OutlookIntegration(client_id=client_id)
    else:
        raise ValueError(f"Unsupported email system: {system}")


def get_email_from_config(client_id: str) -> EmailSystem:
    """Return email from config."""
    from integrations.integration_resolver import resolve_provider
    system = resolve_provider(client_id, "email")
    return get_email_system(client_id=client_id, system=system)