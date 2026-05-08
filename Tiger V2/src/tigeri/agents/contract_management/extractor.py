"""Contract extractor adapters.

Two implementations parallel the OCR adapter pattern:
- ``HeuristicContractExtractor`` — deterministic key:value parser (text only)
- ``ClaudeContractExtractor`` — Claude vision-capable, handles text/images/PDFs

Selected by the same ``TIGERI_OCR_BACKEND`` setting.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from tigeri.core.config import get_settings


class ContractExtractor(Protocol):
    async def extract_terms(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]: ...


def _default_expiry(years: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(days=365 * years)).date().isoformat()


def _normalize(raw: dict) -> dict[str, Any]:
    return {
        "counterparty": str(raw.get("counterparty", "UNKNOWN")),
        "effective_date": raw.get("effective_date") or datetime.now(UTC).date().isoformat(),
        "expiry_date": raw.get("expiry_date") or _default_expiry(),
        "auto_renewal": bool(raw.get("auto_renewal", False)),
        "contract_value": (
            Decimal(str(raw["contract_value"])) if raw.get("contract_value") is not None else None
        ),
        "currency": str(raw.get("currency", "USD")).upper(),
        "key_terms": [
            {"term": str(t.get("term", "")), "value": str(t.get("value", ""))}
            for t in raw.get("key_terms", [])
        ],
    }


class HeuristicContractExtractor:
    """Parses simple ``key: value`` text contracts. Test-friendly.

    Supported keys: counterparty, effective, expiry, auto_renewal, value,
    currency. Unknown keys end up as key_terms entries.
    """

    async def extract_terms(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]:
        if not media_type.startswith("text/"):
            raise ValueError(
                f"HeuristicContractExtractor only handles text/*; got {media_type}"
            )
        kv: dict[str, str] = {}
        for line in document_bytes.decode("utf-8").splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                kv[k.strip().lower()] = v.strip()
        known = {"counterparty", "effective", "expiry", "auto_renewal", "value", "currency"}
        return _normalize(
            {
                "counterparty": kv.get("counterparty", "UNKNOWN"),
                "effective_date": kv.get("effective"),
                "expiry_date": kv.get("expiry"),
                "auto_renewal": kv.get("auto_renewal", "false").lower() == "true",
                "contract_value": kv.get("value"),
                "currency": kv.get("currency", "USD"),
                "key_terms": [
                    {"term": k, "value": v} for k, v in kv.items() if k not in known
                ],
            }
        )


_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "llm" / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _decode_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class ClaudeContractExtractor:
    _IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

    def __init__(self, model: str | None = None) -> None:
        from anthropic import AsyncAnthropic

        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self._model = model or settings.llm_agent_model

    async def extract_terms(
        self, document_bytes: bytes, media_type: str = "text/plain"
    ) -> dict[str, Any]:
        if media_type.startswith("text/"):
            user_blocks: list[dict] = [
                {
                    "type": "text",
                    "text": (
                        "Extract structured terms from this contract. "
                        "Respond with JSON only.\n\n<document>\n"
                        f"{document_bytes.decode('utf-8')}\n</document>"
                    ),
                }
            ]
        elif media_type in self._IMAGE_TYPES:
            user_blocks = [
                {"type": "text", "text": "Extract structured terms from this contract page. JSON only."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(document_bytes).decode("ascii"),
                    },
                },
            ]
        elif media_type == "application/pdf":
            user_blocks = [
                {"type": "text", "text": "Extract structured terms from this contract PDF. JSON only."},
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
            raise ValueError(f"unsupported media_type: {media_type}")

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _load_prompt("contract_extract.md"),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_blocks}],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        return _normalize(_decode_json(text))


def default_contract_extractor() -> ContractExtractor:
    settings = get_settings()
    if (settings.ocr_backend or "heuristic").lower() == "claude" and settings.anthropic_api_key:
        return ClaudeContractExtractor()
    return HeuristicContractExtractor()
