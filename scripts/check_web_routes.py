"""Smoke test for web cabinet routes.

Usage:
    python scripts/check_web_routes.py [--base-url http://localhost:8000] [--cookie SESSION_COOKIE]

Checks all major GET web routes and reports status, duration, and errors.
"""

import argparse
import sys
import time

import httpx

ROUTES = [
    "/",
    "/orders",
    "/sales",
    "/pricing",
    "/mrc-pricing",
    "/profit",
    "/stocks",
    "/plan-fact",
    "/analytics",
    "/settings",
    "/accounts",
    "/subscription",
    "/admin/commissions",
    "/admin/commissions/check-ozon",
    "/products",
    "/product-matching",
    "/alerts",
    "/data-quality",
    "/control",
    "/returns",
    "/break-even",
    "/costs",
    "/profile",
]

WARN_THRESHOLD_MS = 2000
ERROR_THRESHOLD_MS = 5000


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test web cabinet routes")
    parser.add_argument("--base-url", default="http://localhost:8000/web")
    parser.add_argument("--cookie", default="", help="seller_web_session cookie value")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    cookies = {}
    if args.cookie:
        cookies["seller_web_session"] = args.cookie

    client = httpx.Client(
        follow_redirects=True,
        timeout=args.timeout,
        cookies=cookies,
    )

    results = []
    for route in ROUTES:
        url = f"{base_url}{route}"
        start = time.monotonic()
        try:
            response = client.get(url)
            duration_ms = round((time.monotonic() - start) * 1000)
            status = response.status_code
            error = None
            if status >= 500:
                error = f"HTTP {status}"
            elif status == 401:
                error = "Unauthorized (no cookie?)"
        except httpx.TimeoutException:
            duration_ms = round((time.monotonic() - start) * 1000)
            status = 0
            error = "TIMEOUT"
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000)
            status = 0
            error = f"{type(exc).__name__}: {exc}"

        results.append((route, status, duration_ms, error))

    print(f"\n{'Route':<45} {'Status':>6} {'Duration':>10} {'Result'}")
    print("-" * 90)

    warnings = 0
    errors = 0
    for route, status, duration_ms, error in results:
        if error:
            flag = "ERROR"
            errors += 1
        elif duration_ms > ERROR_THRESHOLD_MS:
            flag = "SLOW!"
            errors += 1
        elif duration_ms > WARN_THRESHOLD_MS:
            flag = "WARN"
            warnings += 1
        else:
            flag = "OK"

        status_str = str(status) if status else "—"
        duration_str = f"{duration_ms}ms"
        error_str = error or flag

        print(f"{route:<45} {status_str:>6} {duration_str:>10} {error_str}")

    print("-" * 90)
    print(f"Total: {len(results)} routes, {warnings} warnings, {errors} errors")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
