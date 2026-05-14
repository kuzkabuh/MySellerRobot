"""version: 1.0.0
description: Unit tests for Excel cost import validation.
updated: 2026-05-14
"""

from pathlib import Path

from app.services.excel_cost_import import ExcelCostImportService


def test_create_and_parse_template(tmp_path: Path) -> None:
    service = ExcelCostImportService()
    path = service.create_template(tmp_path / "costs.xlsx")

    rows, errors = service.parse(path)

    assert not errors
    assert rows[0].seller_article == "SKU-001"
    assert rows[0].tax_rate == rows[0].tax_rate.__class__("0.06")
