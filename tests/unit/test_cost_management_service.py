"""version: 1.0.0
description: Unit tests for cost management parsing.
updated: 2026-05-14
"""

from decimal import Decimal

import pytest

from app.services.cost_management_service import CostManagementError, parse_manual_cost_line


def test_parse_manual_cost_line() -> None:
    article, cost, package, additional, tax_rate, valid_from = parse_manual_cost_line(
        "SKU-001; 520; 25; 3.5; 6; 2026-05-14"
    )

    assert article == "SKU-001"
    assert cost == Decimal("520.00")
    assert package == Decimal("25.00")
    assert additional == Decimal("3.50")
    assert tax_rate == Decimal("0.0600")
    assert valid_from.year == 2026


def test_parse_manual_cost_line_rejects_bad_format() -> None:
    with pytest.raises(CostManagementError):
        parse_manual_cost_line("SKU-001; 520")
