"""Regression test for _load_mrc_page_data with active auto promotions."""


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

    assert (
        first_assignment_idx is not None
    ), "has_active_auto_promotions must be assigned in the function"
    assert first_usage_idx is not None, "has_active_auto_promotions must be used in the function"
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
    assert stats_query_idx < enrichment_idx, "Stats queries must come before product enrichment"


def test_wb_nm_id_for_product_no_name_error():
    """Verify wb_nm_id_for_product is defined before use in _mrc_pricing_content.

    The bug was: wb_nm_id_for_product was used at line ~2848 inside the
    STATUS_AUTO_REQUIRED_PRICE_UNKNOWN branch but was only defined in a
    different code path (line ~1948), causing NameError.

    Fix: define wb_nm_id_for_product = nm_id inside the branch, with a
    fallback when nmID is not found.

    This test verifies the source code does not contain an undefined reference.
    """
    import inspect

    from app.web.route_modules.mrc_pricing import _mrc_pricing_content

    source = inspect.getsource(_mrc_pricing_content)

    # The fixed code should define wb_nm_id_for_product inside the
    # STATUS_AUTO_REQUIRED_PRICE_UNKNOWN branch
    assert "wb_nm_id_for_product = nm_id" in source, (
        "wb_nm_id_for_product must be assigned from nm_id in the "
        "STATUS_AUTO_REQUIRED_PRICE_UNKNOWN branch"
    )

    # Should also handle the case when nm_id is None
    assert (
        "nmID не найден" in source
        or "nm_id is None" in source
        or "if wb_nm_id_for_product" in source
    ), "Code should handle missing nmID gracefully"


def test_extract_nm_id_from_external_product_id():
    """Verify _extract_nm_id extracts nmID from external_product_id."""
    from unittest.mock import MagicMock

    from app.web.route_modules.mrc_pricing import _extract_nm_id

    product = MagicMock()
    product.marketplace_article = "ART-123"
    product.external_product_id = "345455998"

    nm_id = _extract_nm_id(product)
    assert nm_id == 345455998


def test_extract_nm_id_from_marketplace_article_fallback():
    """Verify _extract_nm_id falls back to marketplace_article."""
    from unittest.mock import MagicMock

    from app.web.route_modules.mrc_pricing import _extract_nm_id

    product = MagicMock()
    product.marketplace_article = "345455998"
    product.external_product_id = None

    nm_id = _extract_nm_id(product)
    assert nm_id == 345455998


def test_wb_product_price_import_in_auto_promo_service():
    """Verify WbProductPrice is importable at module level in wb_auto_promo_price_service.

    The bug was: WbProductPrice was imported locally inside
    build_recommendations_for_conditions (line 285), but
    _get_current_wb_price_from_db (line 337) is a separate method that
    also uses WbProductPrice, causing NameError.

    Fix: move the import to the top-level imports block.
    """
    import inspect

    from app.services.pricing.wb_auto_promo_price_service import (
        WbAutoPromoPriceService,
        WbProductPrice,
    )

    # WbProductPrice should be importable from the module
    assert WbProductPrice is not None

    # Verify the import is at module level (top-level), not inside a method
    source = inspect.getsource(WbAutoPromoPriceService)
    # The method should NOT contain a local import of WbProductPrice
    assert (
        "from app.models.domain import WbProductPrice" not in source
    ), "WbProductPrice must be imported at module level, not inside a method"
