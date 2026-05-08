"""Contain sanitiser backend logic."""
import re
import unicodedata

MAX_INPUT_LENGTH = 4000

_SQL_MUTATION_PATTERNS = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE|DELETE\s+FROM|"
    r"INSERT\s+INTO|ALTER\s+TABLE|EXEC\s*\(|EXECUTE\s*\(|xp_|sp_cmdshell)\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+previous\s+instructions|ignore\s+all\s+previous|"
    r"forget\s+everything\s+above|you\s+are\s+now\s+a|"
    r"new\s+persona|override\s+previous\s+instructions|"
    r"your\s+new\s+instructions\s+are|jailbreak|dan\s+mode|"
    r"\[SYSTEM\]|\[INST\]|disregard\s+your\s+instructions)",
    re.IGNORECASE,
)

_NULL_BYTE = re.compile(r"\x00")
_BOUNDARY_MARKERS = re.compile(r"</?untrusted>")


def is_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_PATTERNS.search(text))


def is_sql_injection(text: str) -> bool:
    return bool(_SQL_MUTATION_PATTERNS.search(text))


def _normalise_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def sanitise_input(raw: str) -> str:
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw[:MAX_INPUT_LENGTH]
    raw = _normalise_unicode(raw)
    raw = _NULL_BYTE.sub("", raw)
    raw = _BOUNDARY_MARKERS.sub("", raw)
    if is_prompt_injection(raw):
        raw = _INJECTION_PATTERNS.sub("[FILTERED]", raw)
    return f"<untrusted>{raw}</untrusted>"


def sanitise_db_value(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    value = value[:500]
    value = _normalise_unicode(value)
    value = _NULL_BYTE.sub("", value)
    value = _BOUNDARY_MARKERS.sub("", value)
    if _SQL_MUTATION_PATTERNS.search(value):
        value = _SQL_MUTATION_PATTERNS.sub("[BLOCKED]", value)
    return value.strip()


def sanitise_dict(data: dict) -> dict:
    cleaned = {}
    for k, v in data.items():
        if isinstance(v, str):
            cleaned[k] = sanitise_db_value(v)
        elif isinstance(v, dict):
            cleaned[k] = sanitise_dict(v)
        elif isinstance(v, list):
            cleaned[k] = [
                sanitise_db_value(i) if isinstance(i, str) else i
                for i in v
            ]
        else:
            cleaned[k] = v
    return cleaned


def strip_boundary_markers(text: str) -> str:
    return _BOUNDARY_MARKERS.sub("", text)