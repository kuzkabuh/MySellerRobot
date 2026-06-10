"""version: 1.0.0
description: Smoke tests for FastAPI application factory (create_app).
updated: 2026-06-10
"""


def test_create_app() -> None:
    """create_app() must return a FastAPI instance without errors."""
    from app.api.main import create_app

    app = create_app()
    assert app is not None
    assert app.title == "Seller Profit Bot API"


def test_create_app_has_routes() -> None:
    """create_app() must register all expected routers."""
    from app.api.main import create_app

    app = create_app()
    route_paths = [route.path for route in app.routes]

    # System routes
    assert "/health" in route_paths
    assert "/robots.txt" in route_paths
    assert "/" in route_paths

    # Web routes
    assert any("/web/" in p for p in route_paths)

    # Webhook routes
    assert any("webhook" in p.lower() for p in route_paths)
