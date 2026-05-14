"""version: 1.0.0
description: Token encryption and masking helpers.
updated: 2026-05-14
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def generate_encryption_key() -> str:
    """Generate a Fernet key for ENCRYPTION_KEY."""

    return Fernet.generate_key().decode()


class TokenCipher:
    """Encrypt and decrypt marketplace credentials."""

    def __init__(self, key: str | None = None) -> None:
        raw_key = key or get_settings().encryption_key.get_secret_value()
        self._fernet = Fernet(raw_key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Не удалось расшифровать сохранённый ключ") from exc


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Mask sensitive value for Telegram UI."""

    if not value:
        return "не задан"
    if len(value) <= visible * 2:
        return "***"
    return f"{value[:visible]}...{value[-visible:]}"
