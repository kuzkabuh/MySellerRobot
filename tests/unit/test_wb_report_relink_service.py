from app.services.wb_report_relink_service import normalize_report_srid


def test_relink_normalizes_srid_for_matching() -> None:
    assert normalize_report_srid("  AbC 123 \n") == "abc123"


def test_relink_keeps_empty_srid_unmatched() -> None:
    assert normalize_report_srid("") is None
