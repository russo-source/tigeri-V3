from ulid import ULID


def new_id(prefix: str = "") -> str:
    uid = str(ULID())
    return f"{prefix}_{uid}" if prefix else uid


def trace_id() -> str:
    return new_id("trace")
