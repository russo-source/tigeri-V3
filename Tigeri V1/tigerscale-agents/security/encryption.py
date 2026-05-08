"""Contain encryption backend logic."""
from cryptography.fernet import Fernet
from config.settings import settings

_fernet = None

def _get_fernet() -> Fernet:
    """Return fernet."""
    global _fernet
    if _fernet is None:
        key = settings.secret_encryption_key
        if not key:
            raise ValueError("SECRET_ENCRYPTION_KEY not set")
        _fernet = Fernet(key.encode())
    return _fernet

def encrypt_secret(value: str) -> str:
    """Execute encrypt secret."""
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()

def decrypt_secret(value: str) -> str:
    """Execute decrypt secret."""
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception as e:
        import sys
        print(f"[ERROR] decrypt_secret failed: {e}", file=sys.stderr)
        raise