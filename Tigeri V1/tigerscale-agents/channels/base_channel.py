"""Contain base channel backend logic."""
from abc import ABC, abstractmethod
from typing import Optional
import logging

class Message:
    """Represent the Message component and its related behavior."""
    def __init__(
        self,
        client_id: str,
        sender: str,
        content: str,
        channel: str,
        raw: Optional[dict] = None,
        mime_type: str = "",
        filename: str = "",
        file_bytes: bytes = b"",
    ):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self.sender = sender
        self.content = content
        self.channel = channel
        self.raw = raw or {}
        self.mime_type = mime_type
        self.filename = filename
        self.file_bytes = file_bytes

    def __repr__(self):
        """Return a developer-friendly string representation of this object."""
        return f"Message(client_id={self.client_id}, channel={self.channel}, sender={self.sender})"


class BaseChannel(ABC):

    """Represent the BaseChannel component and its related behavior."""
    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self._logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

    @abstractmethod
    def parse(self, payload: dict) -> Message:
        """Parse the requested operation."""
        pass

    @abstractmethod
    def send(self, recipient: str, message: str) -> bool:
        """Send the requested operation."""
        pass

    def log(self, message: str, level: str = "INFO") -> None:
        """Execute log for BaseChannel."""
        lvl = getattr(logging, level.upper(), logging.INFO)
        self._logger.log(lvl, "[%s] %s", self.client_id, message)