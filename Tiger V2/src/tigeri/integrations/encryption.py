"""Fernet wrapper for encrypting OAuth refresh tokens at rest."""

from cryptography.fernet import Fernet, InvalidToken

from tigeri.core.config import get_settings


class EncryptionUnavailable(RuntimeError):
    """Raised when ``TIGERI_SECRET_ENCRYPTION_KEY`` is missing or invalid."""


def _fernet() -> Fernet:
    key = get_settings().secret_encryption_key
    if not key:
        raise EncryptionUnavailable(
            "TIGERI_SECRET_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())\"` "
            "and put it in /etc/tigeri/tigeri.env"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, InvalidToken) as e:
        raise EncryptionUnavailable(f"invalid Fernet key: {e}") from e


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
