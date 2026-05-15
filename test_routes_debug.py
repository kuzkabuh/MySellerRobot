"""Debug script to test web routes."""
import asyncio
from app.api.main import create_app
from httpx import AsyncClient, ASGITransport

async def test_routes():
    app = create_app()

    # Test without authentication (should get 401)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        print("Testing routes without authentication:")

        routes_to_test = [
            "/web/",
            "/web/orders",
            "/web/profit",
            "/web/products",
            "/web/plan-fact",
        ]

        for route in routes_to_test:
            response = await client.get(route, follow_redirects=False)
            print(f"  {route:25} -> {response.status_code} {response.reason_phrase}")
            if response.status_code == 404:
                print(f"    Body: {response.text[:200]}")

if __name__ == "__main__":
    asyncio.run(test_routes())
