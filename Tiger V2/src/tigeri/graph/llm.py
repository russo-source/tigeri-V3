"""LangChain Anthropic factory with prompt caching enabled."""

from langchain_anthropic import ChatAnthropic

from tigeri.core.config import get_settings


def agent_llm(*, max_tokens: int = 1024) -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.llm_agent_model,
        api_key=settings.anthropic_api_key or None,
        max_tokens=max_tokens,
        # Prompt caching applies to the system prompt + tools — see the
        # cache_control markers on system blocks in the per-agent graph.
    )


def reasoning_llm(*, max_tokens: int = 4096) -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.llm_reasoning_model,
        api_key=settings.anthropic_api_key or None,
        max_tokens=max_tokens,
    )
