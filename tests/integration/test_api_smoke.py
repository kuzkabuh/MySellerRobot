"""version: 1.0.0
description: Smoke tests for FastAPI app construction.
updated: 2026-05-14
"""

from app.api.main import create_app


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Seller Profit Bot API"
