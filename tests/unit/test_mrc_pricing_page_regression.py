"""Regression test for _load_mrc_page_data with active auto promotions."""

import pytest


def test_unbound_local_error_is_fixed():
    """Verify that has_active_auto_promotions is defined before use.

    The bug was: has_active_auto_promotions was used at line ~1482
    but only defined at line ~1619, causing UnboundLocalError.

    Fix: moved stats queries to the beginning of _load_mrc_page_data
    with safe defaults.

    This test verifies the source code structure.
    """
    import inspect
    from app.web.route_modules.mrc_pricing import _load_mrc_page_data

    source = inspect.getsource(_load_mrc_page_data)
    lines = source.split("\n")

    # Find where has_active_auto_promotions is first assigned
    first_assignment_idx = None
    first_usage_idx = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments and the safe defaults block
        if stripped.startswith("#"):
            continue

        # First assignment (not in safe defaults block)
        if "has_active_auto_promotions =" in stripped and first_assignment_idx is None:
            first_assignment_idx = idx

        # Usage in if statement
        if "if has_active_auto_promotions" in stripped and first_usage_idx is None:
            first_usage_idx = idx

    assert first_assignment_idx is not None, (
        "has_active_auto_promotions must be assigned in the function"
    )
    assert first_usage_idx is not None, (
        "has_active_auto_promotions must be used in the function"
    )
    assert first_assignment_idx < first_usage_idx, (
        f"has_active_auto_promotions must be assigned (line {first_assignment_idx}) "
        f"before it is used (line {first_usage_idx})"
    )


def test_safe_defaults_are_present():
    """Verify safe defaults are declared at the start of the function."""
    import inspect
    from app.web.route_modules.mrc_pricing import _load_mrc_page_data

    source = inspect.getsource(_load_mrc_page_data)

    # Check that safe defaults block exists
    assert "has_active_auto_promotions = False" in source
    assert "active_auto_promotions_count = 0" in source
    assert "active_regular_promotions_count = 0" in source
    assert "active_promotions_count = 0" in source
    assert "nomenclatures_count = 0" in source
    assert "nomenclatures_synced = False" in source
    assert "has_sync_errors = False" in source


def test_stats_queries_before_product_enrichment():
    """Verify that promotion stats are queried before product enrichment loop."""
    import inspect
    from app.web.route_modules.mrc_pricing import _load_mrc_page_data

    source = inspect.getsource(_load_mrc_page_data)
    lines = source.split("\n")

    # Find key markers
    stats_query_idx = None
    enrichment_idx = None
    for idx, line in enumerate(lines):
        if "Fetch promotion stats FIRST" in line:
            stats_query_idx = idx
        if "Enrich with MRC calculation" in line:
            enrichment_idx = idx

    assert stats_query_idx is not None, "Stats query marker not found"
    assert enrichment_idx is not None, "Enrichment marker not found"
    assert stats_query_idx < enrichment_idx, (
        "Stats queries must come before product enrichment"
    )
