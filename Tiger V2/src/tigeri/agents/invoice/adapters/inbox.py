"""Generic inbox/upload ingress (vendor-agnostic per catalog rule)."""

import base64
import mimetypes
from pathlib import Path
from typing import Protocol


class InboxAdapter(Protocol):
    """Returns the raw document body. fetch_document() returns text only (legacy);
    fetch_bytes() returns raw bytes + media_type so OCR adapters can do vision."""

    async def fetch_document(self, content_ref: str) -> str: ...
    async def fetch_bytes(self, content_ref: str) -> tuple[bytes, str]: ...


class LocalInboxAdapter:
    """Slice 1 stub. Supports four ref schemes:

    - ``inline:<text>`` — inline text content (used by tests / dev)
    - ``file://<path>`` — local file (text or binary; media_type guessed from extension)
    - ``data:<media_type>;base64,<base64>`` — RFC 2397 data URL (used by frontend uploads)
    - ``s3://bucket/key`` — handled by S3InboxAdapter (here this raises)
    """

    async def fetch_document(self, content_ref: str) -> str:
        body, _ = await self.fetch_bytes(content_ref)
        return body.decode("utf-8")

    async def fetch_bytes(self, content_ref: str) -> tuple[bytes, str]:
        if content_ref.startswith("inline:"):
            return content_ref[len("inline:") :].encode("utf-8"), "text/plain"
        if content_ref.startswith("file://"):
            path = Path(content_ref[len("file://") :])
            data = path.read_bytes()
            media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return data, media
        if content_ref.startswith("data:"):
            header, _, b64 = content_ref.partition(",")
            media = header.split(";")[0].split(":")[1] or "application/octet-stream"
            return base64.b64decode(b64), media
        raise ValueError(f"unsupported content_ref scheme: {content_ref}")
