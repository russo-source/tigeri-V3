"""OCR adapters.

Two implementations:
- ``HeuristicOCRAdapter`` — deterministic key:value parser used by tests so
  the suite stays offline.
- ``ClaudeOCRAdapter`` — Claude Sonnet 4.6 vision; handles text, images
  (jpeg/png/webp/gif), and PDFs. Selected when the Anthropic key is configured
  and ``TIGERI_OCR_BACKEND=claude`` (the default in production).
"""

import base64
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from tigeri.core.config import get_settings


class OCRAdapter(Protocol):
    async def extract_fields(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]: ...


class HeuristicOCRAdapter:
    """Parses simple ``key: value`` text invoices. Used by the test suite and
    by dev environments without an Anthropic key."""

    _AMOUNT_RE = re.compile(r"([0-9]+\.[0-9]{2})")

    async def extract_fields(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]:
        if not media_type.startswith("text/"):
            raise ValueError(
                f"HeuristicOCRAdapter only handles text/*; got {media_type}"
            )
        document_text = document_bytes.decode("utf-8")
        kv: dict[str, str] = {}
        for line in document_text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                kv[k.strip().lower()] = v.strip()
        amount_total = Decimal(kv.get("total", "0.00"))
        tax_total = Decimal(kv.get("tax", "0.00"))
        return {
            "vendor_name": kv.get("vendor", "UNKNOWN"),
            "currency": kv.get("currency", "USD"),
            "amount_total": amount_total,
            "tax_total": tax_total,
            "tax_rate_label": kv.get("tax_rate") or kv.get("tax_rate_label") or "",
            "due_date": kv.get("due"),
            "invoice_number": kv.get("invoice", "UNKNOWN"),
            "po_reference": kv.get("po"),
            "line_items": [
                {
                    "description": "line",
                    "qty": Decimal("1"),
                    "unit_price": amount_total - tax_total,
                }
            ],
        }


_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "llm" / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _safe_decimal(value: Any, default: str = "0") -> Decimal:
    """Claude vision often returns null / "" / "N/A" for missing decimals."""
    if value is None:
        return Decimal(default)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "na"}:
        return Decimal(default)
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return Decimal(default)


def _normalize(raw: dict) -> dict[str, Any]:
    amount_total = _safe_decimal(raw.get("amount_total"))
    tax_total = _safe_decimal(raw.get("tax_total"))
    vendor = str(raw.get("vendor_name") or "UNKNOWN")
    line_items = [
        {
            "description": str(li.get("description") or ""),
            "qty": _safe_decimal(li.get("qty"), default="1"),
            "unit_price": _safe_decimal(li.get("unit_price")),
        }
        for li in (raw.get("line_items") or [])
    ]
    # Synthesise one line item when the source text only described totals
    # (e.g. "raise an invoice for $5000 to Acme"). Otherwise the downstream
    # invoice has a header but zero rows, which makes Xero refuse the post
    # and the chat card render an empty grid. We use the net (amount minus
    # tax) so summing the lines + tax recovers amount_total.
    if not line_items and amount_total > Decimal("0"):
        line_items = [
            {
                "description": f"Services rendered — {vendor}",
                "qty": Decimal("1"),
                "unit_price": amount_total - tax_total,
            }
        ]
    return {
        "vendor_name": vendor,
        "currency": str(raw.get("currency") or "USD").upper(),
        "amount_total": amount_total,
        "tax_total": tax_total,
        "tax_rate_label": str(raw.get("tax_rate_label") or raw.get("tax_rate") or ""),
        "due_date": raw.get("due_date"),
        "invoice_number": str(raw.get("invoice_number") or "UNKNOWN"),
        "po_reference": raw.get("po_reference"),
        "line_items": line_items,
    }


def _decode_json_blob(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class ClaudeOCRAdapter:
    """Claude vision OCR. Sends the document directly to Claude Sonnet 4.6
    with the cached extraction prompt; works for text, images, and PDFs.
    """

    _IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    _PDF_TYPE = "application/pdf"

    def __init__(self, model: str | None = None) -> None:
        from anthropic import AsyncAnthropic

        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self._model = model or settings.llm_agent_model

    async def extract_fields(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]:
        if media_type.startswith("text/"):
            user_blocks: list[dict] = [
                {
                    "type": "text",
                    "text": (
                        "Extract structured fields from this invoice. "
                        "Respond with JSON only.\n\n<document>\n"
                        f"{document_bytes.decode('utf-8')}\n</document>"
                    ),
                }
            ]
        elif media_type in self._IMAGE_TYPES:
            user_blocks = [
                {
                    "type": "text",
                    "text": "Extract structured fields from this invoice. Respond with JSON only.",
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(document_bytes).decode("ascii"),
                    },
                },
            ]
        elif media_type == self._PDF_TYPE:
            user_blocks = [
                {
                    "type": "text",
                    "text": "Extract structured fields from this invoice PDF. Respond with JSON only.",
                },
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(document_bytes).decode("ascii"),
                    },
                },
            ]
        else:
            raise ValueError(f"unsupported media_type for ClaudeOCRAdapter: {media_type}")

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _load_prompt("invoice_extract.md"),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_blocks}],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        return _normalize(_decode_json_blob(text))


def default_ocr_adapter() -> OCRAdapter:
    """Pick OCR backend based on settings.

    ``TIGERI_OCR_BACKEND=claude`` requires ``ANTHROPIC_API_KEY``. Anything else
    (or missing key) falls back to the heuristic adapter so tests stay offline.
    """

    settings = get_settings()
    backend = (settings.ocr_backend or "heuristic").lower()
    if backend == "claude" and settings.anthropic_api_key:
        return ClaudeOCRAdapter()
    return HeuristicOCRAdapter()
