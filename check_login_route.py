"""Check if login route is registered correctly."""

from app.api.main import create_app

app = create_app()

print("All /web routes:")
for route in app.routes:
    if hasattr(route, "path") and "/login" in route.path:
        methods = getattr(route, "methods", set())
        methods_str = str(list(methods) if methods else ["GET"])
        print(f"  {methods_str:20} {route.path}")
        print(f"    Name: {route.name}")
        print(f"    Endpoint: {route.endpoint.__name__ if hasattr(route, 'endpoint') else 'N/A'}")
        print()
