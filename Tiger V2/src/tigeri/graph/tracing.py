"""LangSmith bootstrap.

LangSmith reads `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and
`LANGSMITH_TRACING` from the process environment. We surface those values
through Tigeri settings so they're declared in one place.
"""

import os

from tigeri.core.config import get_settings


def configure_langsmith() -> bool:
    """Sync Tigeri settings → LangSmith env vars. Returns True if tracing is on."""

    settings = get_settings()
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        os.environ.pop("LANGSMITH_TRACING", None)
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
