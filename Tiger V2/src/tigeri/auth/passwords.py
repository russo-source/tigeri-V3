"""Bcrypt password hashing. Cost factor 12 per the spec ("≥ 12")."""

import bcrypt

_COST_FACTOR = 12


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("password is empty")
    salt = bcrypt.gensalt(rounds=_COST_FACTOR)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, stored_hash: str | None) -> bool:
    if not stored_hash or not plaintext:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
