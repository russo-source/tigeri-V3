import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from tigeri.core.config import get_settings

_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


class AnthropicLLM:
    """Wrapper around AsyncAnthropic with prompt caching enabled.

    Long-lived system blocks (extraction prompts, agent catalog) are marked
    with cache_control to amortise cost across tenant requests.
    """

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key or None)
        self._agent_model = settings.llm_agent_model
        self._reasoning_model = settings.llm_reasoning_model

    async def extract_invoice(self, document_text: str) -> dict[str, Any]:
        system_blocks = [
            {
                "type": "text",
                "text": _load_prompt("invoice_extract.md"),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        message = await self._client.messages.create(
            model=self._agent_model,
            max_tokens=2048,
            system=system_blocks,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract structured fields from this invoice document. "
                        "Respond with JSON only.\n\n<document>\n"
                        f"{document_text}\n</document>"
                    ),
                }
            ],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    async def reason_over_catalog(
        self, catalog_summary: str, vertical_json: str, objectives_json: str
    ) -> str:
        system_blocks = [
            {
                "type": "text",
                "text": _load_prompt("reasoning_system.md"),
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": catalog_summary,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        message = await self._client.messages.create(
            model=self._reasoning_model,
            max_tokens=4096,
            system=system_blocks,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"<vertical>{vertical_json}</vertical>\n"
                        f"<objectives>{objectives_json}</objectives>\n\n"
                        "Return ranked agent recommendations as JSON matching the section 4.3 output schema."
                    ),
                }
            ],
        )
        return "".join(block.text for block in message.content if block.type == "text")
