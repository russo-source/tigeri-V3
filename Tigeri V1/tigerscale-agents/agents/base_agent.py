"""Contain base agent backend logic."""
from __future__ import annotations
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any
import anthropic
from config.settings import settings

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Return client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


class BaseAgent(ABC):
    """Represent the BaseAgent component and its related behavior."""

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self.model = "claude-sonnet-4-6"
        self.max_tokens = 4096
        self.max_loop_iterations = 10

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return system prompt."""
        pass

    def get_tools(self) -> list[dict]:
        return []

    def execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        return {"error": f"Tool not implemented: {tool_name}"}

    def run_loop(self, task: dict) -> dict:
        """
        Autonomous tool-use loop.
        Claude picks tools, we execute them, feed results back, repeat
        until stop_reason == end_turn or max iterations reached.
        """
        message = task.get("message", "")
        sender  = task.get("sender", "")

        context_str = ""
        try:
            from core.conversation import _build_enriched_message, _get_context
            ctx_turns   = _get_context(sender, self.client_id)
            context_str = _build_enriched_message(
                message, ctx_turns,
                sender=sender,
                client_id=self.client_id,
                domain=task.get("domain", ""),
            )
        except Exception:
            context_str = message

        tools = self.get_tools()

        messages: list[dict] = [{"role": "user", "content": context_str or message}]

        last_result: dict = {}
        iterations = 0

        while iterations < self.max_loop_iterations:
            iterations += 1

            try:
                kwargs: dict[str, Any] = {
                    "model":      self.model,
                    "max_tokens": self.max_tokens,
                    "system":     self.get_system_prompt(),
                    "messages":   messages,
                }
                if tools:
                    kwargs["tools"] = tools

                response = _get_client().messages.create(**kwargs)
            except Exception as exc:
                logger.error(
                    "run_loop LLM call failed client=%s agent=%s iter=%d: %s",
                    self.client_id, self.__class__.__name__, iterations, exc,
                )
                raise

            stop_reason = response.stop_reason

            # collect assistant content blocks
            assistant_content: list[dict] = []
            tool_use_blocks:   list[Any]  = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                    last_result["message"] = block.text
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type":  "tool_use",
                        "id":    block.id,
                        "name":  block.name,
                        "input": block.input,
                    })
                    tool_use_blocks.append(block)

            messages.append({"role": "assistant", "content": assistant_content})

            if stop_reason == "end_turn" or not tool_use_blocks:
                break

            # execute each tool and build tool_result blocks
            tool_results: list[dict] = []

            for block in tool_use_blocks:
                tool_name  = block.name
                tool_input = block.input or {}

                logger.info(
                    "run_loop tool_call client=%s agent=%s tool=%s iter=%d",
                    self.client_id, self.__class__.__name__, tool_name, iterations,
                )

                try:
                    result = self.execute_tool(tool_name, {**tool_input, **self._task_meta(task)})
                except Exception as exc:
                    logger.error(
                        "execute_tool failed client=%s tool=%s: %s",
                        self.client_id, tool_name, exc,
                    )
                    result = {"error": str(exc)}

                last_result = result

                from agents.base_tools import format_result, tool_result as make_tool_result
                tool_results.append(make_tool_result(
                    tool_use_id=block.id,
                    content=format_result(result),
                    is_error=bool(result.get("error")),
                ))

            messages.append({"role": "user", "content": tool_results})

        if iterations >= self.max_loop_iterations:
            logger.warning(
                "run_loop hit max iterations client=%s agent=%s",
                self.client_id, self.__class__.__name__,
            )

        status = "error" if last_result.get("error") else "success"
        return {
            "status":  status,
            "message": last_result.get("message", ""),
            "result":  last_result,
            "action":  last_result.get("action", ""),
            "loops":   iterations,
        }

    def _task_meta(self, task: dict) -> dict:
        return {
            "_sender":     task.get("sender", ""),
            "_channel":    task.get("channel", ""),
            "_client_id":  self.client_id,
            "_task_id":    task.get("task_id", ""),
        }

    def run(self, task: dict) -> dict:
        from security.authorization import assert_authorized

        action = task.get("action") or task.get("message", "")
        sender_id = task.get("sender_id", "")
        denial = assert_authorized(
            self.client_id, sender_id, action, task.get("message", "")
        )
        if denial:
            return denial

        agent_name = self.__class__.__name__
        intent = task.get("intent", "unknown")
        sender = task.get("sender", "")
        result: dict = {}

        try:
            result = self._run(task)
        except Exception as exc:
            logger.error(
                "_run raised client=%s agent=%s: %s",
                self.client_id, agent_name, exc, exc_info=True,
            )
            graceful = self._graceful_error(task.get("message", ""), exc)
            result = {"status": "error", "message": graceful}

        self._record_outcome(intent, result)

        if sender:
            result_status = result.get("status", "")
            should_clear = (
                result_status == "success"
                and result.get("action") not in ("approve", "send", "remind")
            ) or result_status == "duplicate"
            if should_clear:
                try:
                    from core.conversation import clear_pending_intent
                    clear_pending_intent(sender=sender, client_id=self.client_id)
                except Exception as e:
                    logger.debug("clear_pending_intent non-fatal client=%s: %s", self.client_id, e)

        if (
            sender
            and result.get("status") == "success"
            and result.get("action") == "create"
            and result.get("invoice")
        ):
            try:
                from core.conversation import save_action_context
                invoice: dict = result["invoice"]
                inv_num = invoice.get("invoice_number", "")
                if inv_num and inv_num not in ("Pending sync", "pending", ""):
                    save_action_context(
                        sender=sender,
                        client_id=self.client_id,
                        domain="invoice",
                        payload={
                            "invoice_number": inv_num,
                            "vendor":         invoice.get("vendor", ""),
                            "amount":         str(invoice.get("amount", "")),
                            "currency":       invoice.get("currency", "USD"),
                            "action":         "create",
                        },
                    )
            except Exception as e:
                logger.debug("save_action_context invoice non-fatal client=%s: %s", self.client_id, e)

        return result

    def _graceful_error(self, message: str, exc: Exception) -> str:
        """Use LLM to generate a helpful recovery message instead of static error."""
        try:
            error_hint = str(exc)[:200]
            prompt = (
                "You are a helpful financial assistant. "
                "Something went wrong processing the user's request. "
                "Don't mention technical errors or say 'something went wrong'. "
                "Instead, acknowledge what they were trying to do and guide them "
                "to try again with a clearer example. Be warm, brief, and helpful. "
                "Max 2 sentences."
            )
            response = _get_client().messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system=prompt,
                messages=[{
                    "role": "user",
                    "content": f"User said: '{message}'\nError hint: {error_hint}"
                }],
            )
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    return block.text.strip()
        except Exception as e:
            logger.warning("_graceful_error LLM fallback failed: %s", e)
        return "I couldn't process that request. Could you try rephrasing? For example: 'create invoice for Acme USD 500 for consulting services'"
    
    @abstractmethod
    def _run(self, task: dict) -> dict:
        """Run the requested operation."""
        pass

    def call_llm(
        self,
        task: str,
        context: str = "",
        intent: str = "",
    ) -> str:
        """Execute call llm for BaseAgent."""
        content = f"Context:\n{context}\n\nTask:\n{task}" if context else task
        try:
            response = _get_client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": content}],
            )
            for block in response.content:
                if block.type == "text":
                    return block.text.strip()
            raise ValueError("LLM returned empty response")
        except Exception as e:
            logger.error(
                "call_llm failed client=%s agent=%s intent=%s: %s",
                self.client_id, self.__class__.__name__, intent, e,
            )
            raise

    def build_context(
        self,
        memory: str = "",
        knowledge: str = "",
        task: str = "",
    ) -> dict:
        """Build context."""
        return {
            "memory":    memory,
            "knowledge": knowledge,
            "task":      task,
            "client_id": self.client_id,
        }

    def parse_llm_json(self, raw: str) -> dict:
        """Parse llm json."""
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise json.JSONDecodeError(
            "Could not parse JSON from LLM response", text, 0
        )

    def record_entity(
        self,
        entity_name: str,
        domain: str,
        amount: float = 0.0,
        currency: str = "USD",
        late_days: int = 0,
    ) -> None:
        """Execute record entity for BaseAgent."""
        if not entity_name or not entity_name.strip():
            return
        try:
            from core.intelligence_loop import record_entity_interaction
            record_entity_interaction(
                client_id=self.client_id,
                entity_name=entity_name.strip(),
                agent_name=self.__class__.__name__,
                domain=domain,
                amount=amount,
                currency=currency,
                late_days=late_days,
            )
        except Exception as exc:
            logger.debug(
                "record_entity non-fatal client=%s: %s", self.client_id, exc
            )

    def _record_outcome(self, intent: str, result: dict) -> None:
        """Execute record outcome for BaseAgent."""
        try:
            from core.intelligence_loop import record_outcome
            agent_name = self.__class__.__name__
            status = result.get("status", "unknown")
            confidence = float(
                result.get("confidence")
                or (result.get("invoice") or {}).get("confidence")
                or (result.get("raw") or {}).get("confidence")
                or 0.0
            )
            action = result.get("action")
            record_outcome(
                client_id=self.client_id,
                agent_name=agent_name,
                intent=intent,
                action=action,
                status=status,
                confidence=confidence,
            )
        except Exception as exc:
            logger.debug(
                "_record_outcome non-fatal client=%s: %s", self.client_id, exc
            )