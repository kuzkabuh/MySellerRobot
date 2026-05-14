"""version: 1.0.0
description: Unit tests for token encryption helpers.
updated: 2026-05-14
"""

from app.core.security import TokenCipher, generate_encryption_key


def test_token_cipher_roundtrip() -> None:
    cipher = TokenCipher(generate_encryption_key())
    encrypted = cipher.encrypt("secret-token")

    assert encrypted != "secret-token"
    assert cipher.decrypt(encrypted) == "secret-token"
