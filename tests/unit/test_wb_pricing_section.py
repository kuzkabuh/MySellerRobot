"""Tests for the production WB pricing and auto-promotion services."""

from decimal import Decimal


def test_import_wb_promotions_sync_service_does_not_fail() -> None:
    from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService

    assert WbPromotionsSyncService is not None


def test_auto_promo_condition_required_price_from_direct_fields() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    resolver = WbAutoPromoConditionResolver()
    detail = {"nomenclatures": [{"nmID": 1, "requiredPrice": 950}]}

    result = resolver.resolve(detail)

    assert result[0].wb_nm_id == 1
    assert result[0].required_price == Decimal("950.00")
    assert result[0].confidence == "high"


def test_auto_promo_condition_required_price_from_max_price() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"products": [{"id": 2, "maxPrice": "930"}]}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("930.00")


def test_auto_promo_condition_required_price_from_nested_price_info() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"data": {"items": [{"nmId": 3, "priceInfo": {"requiredPrice": 910}}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("910.00")


def test_auto_promo_condition_required_price_from_discount_and_full_price() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"conditions": {"products": [{"nmID": 4, "fullPrice": 1000, "requiredDiscount": 15}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("850.00")
    assert result[0].confidence == "medium"


def test_auto_promo_condition_finds_any_nested_product_list() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"outer": {"deep": [{"goods": [{"nmID": 5, "actionPrice": 777}]}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].wb_nm_id == 5
    assert result[0].required_price == Decimal("777.00")


def test_recommendation_mrc_1000_required_950_is_can_apply() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_CAN_APPLY,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.lower_bound == Decimal("900.0")
    assert rec.upper_bound == Decimal("1100.0")
    assert rec.recommended_price == Decimal("950")
    assert rec.full_wb_price == 3800
    assert rec.discount == 75
    assert rec.status == STATUS_CAN_APPLY


def test_recommendation_required_850_is_blocked_by_mrc() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_BLOCKED_BY_MRC,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=Decimal("850"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MRC


def test_recommendation_current_940_required_950_is_already_ok() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_ALREADY_OK,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("940"),
        required_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_ALREADY_OK


def test_price_apply_payload_950_discount_75() -> None:
    from app.services.pricing.wb_price_apply_service import WbPriceApplyService

    payload = WbPriceApplyService.build_payload(
        nm_id=123,
        recommended_price=Decimal("950"),
        discount=Decimal("75"),
    )

    assert payload.as_wb_item() == {"nmID": 123, "price": 3800, "discount": 75}
    assert "minPrice" not in payload.as_wb_item()


def test_price_apply_blocks_below_min_price() -> None:
    import pytest

    from app.services.pricing.wb_price_apply_service import WbPriceApplyService

    with pytest.raises(ValueError):
        WbPriceApplyService.build_payload(
            nm_id=123,
            recommended_price=Decimal("900"),
            discount=Decimal("75"),
            min_price=Decimal("950"),
        )


def test_no_required_price_creates_no_required_price_status() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_NO_REQUIRED_PRICE,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=None,
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_NO_REQUIRED_PRICE
    assert rec.recommended_price is None
    assert "raw_payload" in rec.reason


def test_auto_promo_condition_model_columns_covered_by_migrations() -> None:
    """Regression: all model columns must be present in migration chain.

    Prevents UndefinedColumnError when production DB runs migrations.
    Specifically guards against missing max_auto_promo_price and other
    participation fields added in migration 0044.
    """
    import pathlib

    from app.models.domain import WbAutoPromotionCondition

    model_columns = {col.key for col in WbAutoPromotionCondition.__table__.columns}

    expected_columns = {
        "id",
        "user_id",
        "marketplace_account_id",
        "wb_promotion_id",
        "wb_nm_id",
        "seller_article",
        "title",
        "promotion_name",
        "required_price",
        "max_auto_promo_price",
        "wb_condition_discount_percent",
        "current_wb_price",
        "current_full_price",
        "current_discount",
        "current_discounted_price",
        "candidate_discounted_price",
        "condition_type",
        "is_participating",
        "source",
        "confidence",
        "raw_payload",
        "synced_at",
        "created_at",
        "updated_at",
    }

    assert expected_columns.issubset(
        model_columns
    ), f"Model missing columns: {expected_columns - model_columns}"

    migration_dir = pathlib.Path("migrations/versions")
    migration_sources = []
    for f in sorted(migration_dir.glob("*.py")):
        if f.name.startswith("__"):
            continue
        migration_sources.append(f.read_text())

    all_migration_text = "\n".join(migration_sources)
    for col in expected_columns:
        assert col in all_migration_text, f"Column {col!r} must be in some migration file"


def test_pricing_module_imports_without_fastapi_error() -> None:
    """Regression: pricing module must import without FastAPI startup errors.

    Guards against union return types like str | RedirectResponse that
    crash FastAPI at import time.
    """
    from app.web.route_modules.pricing import router

    paths = {route.path for route in router.routes}
    assert "/pricing" in paths
    assert "/pricing/auto-promotions/upload/preview" in paths


def test_auto_promo_mrc_1000_promo_950_is_can_apply() -> None:
    """Scenario: MRC 1000, deviation 10%, min allowed 900, promo max 950.

    Since 950 >= 900 (lower bound), the system should recommend price 950.
    """
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_CAN_APPLY,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        wb_condition_discount_percent=None,
        condition_type="max_price",
        min_price=None,
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_discounted_price == Decimal("950")
    assert rec.candidate_discounted_price == Decimal("950")
    assert rec.mrc_lower_bound == Decimal("900")
    assert rec.reason == "Можно применить цену входа WB для автоакции."


def test_auto_promo_full_price_is_discounted_times_4() -> None:
    """WB full price = discounted_price * 4 (75% discount)."""
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_CAN_APPLY,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        wb_condition_discount_percent=None,
        condition_type="max_price",
        min_price=None,
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_full_price == Decimal("3800")
    assert rec.recommended_discount == 75


def test_auto_promo_blocked_when_below_mrc_lower_bound() -> None:
    """If max_auto_promo_price < mrc_lower_bound, recommendation must be blocked."""
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_BLOCKED_BY_MRC,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("850"),
        wb_condition_discount_percent=None,
        condition_type="max_price",
        min_price=None,
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MRC
    assert rec.recommended_discounted_price is None
    assert "ниже минимально допустимой" in rec.reason


def test_auto_promo_blocked_when_below_min_price() -> None:
    """If max_auto_promo_price < seller minPrice, recommendation must be blocked."""
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_BLOCKED_BY_MIN_PRICE,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        wb_condition_discount_percent=None,
        condition_type="max_price",
        min_price=Decimal("960"),
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MIN_PRICE
    assert rec.recommended_discounted_price is None
    assert "minPrice" in rec.reason


def test_auto_promo_already_eligible_when_current_price_ok() -> None:
    """If current discounted price already <= candidate, no action needed."""
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_ALREADY_ELIGIBLE,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("900"),
        max_auto_promo_price=Decimal("950"),
        wb_condition_discount_percent=None,
        condition_type="max_price",
        min_price=None,
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_ALREADY_ELIGIBLE
    assert rec.recommended_discounted_price is None


def test_auto_promo_candidate_from_discount_percent() -> None:
    """When no max_auto_promo_price, candidate = current_full_price * (1 - discount/100)."""
    from app.services.pricing.wb_auto_promo_participation_service import (
        STATUS_CAN_APPLY,
        WbAutoPromoParticipationService,
    )

    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=None,
        wb_condition_discount_percent=Decimal("76.25"),
        condition_type="discount_projection",
        min_price=None,
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.candidate_discounted_price == Decimal("950.00")
    assert rec.recommended_discounted_price == Decimal("950.00")


def test_migration_chain_has_single_head() -> None:
    """Alembic migration chain must have exactly one head."""
    import subprocess

    result = subprocess.run(
        ["python", "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
    )
    heads = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(heads) == 1, f"Expected 1 head, got {len(heads)}: {heads}"
    assert "20260607_0055" in heads[0]


def test_app_create_succeeds() -> None:
    """FastAPI app must be created without errors."""
    from app.api.main import create_app

    app = create_app()
    assert app is not None
    assert len(app.routes) > 50


def test_health_route_registered() -> None:
    """Health check route must be registered."""
    from app.api.main import create_app

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/health" in paths


def test_api_main_app_import_succeeds() -> None:
    """Importing app.api.main:app must not fail."""
    from app.api.main import app

    assert app is not None


def test_auto_promo_preview_get_route_redirects() -> None:
    """Direct browser GET to preview URL must not produce a 500."""
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/web/pricing/auto-promotions/upload/preview",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/web/pricing")


def test_file_import_models_exist() -> None:
    """WbAutoPromoFileImport and WbAutoPromoFileImportRow models must exist."""
    from app.models.domain import WbAutoPromoFileImport, WbAutoPromoFileImportRow

    assert WbAutoPromoFileImport.__tablename__ == "wb_auto_promo_file_imports"
    assert WbAutoPromoFileImportRow.__tablename__ == "wb_auto_promo_file_import_rows"

    import_cols = {col.key for col in WbAutoPromoFileImport.__table__.columns}
    expected_import_cols = {
        "id",
        "user_id",
        "marketplace_account_id",
        "original_file_name",
        "promotion_name",
        "status",
        "total_rows",
        "valid_rows",
        "error_rows",
        "warning_rows",
        "created_at",
        "updated_at",
        "applied_at",
        "error_text",
    }
    assert expected_import_cols.issubset(
        import_cols
    ), f"File import model missing: {expected_import_cols - import_cols}"

    row_cols = {col.key for col in WbAutoPromoFileImportRow.__table__.columns}
    expected_row_cols = {
        "id",
        "import_id",
        "row_number",
        "wb_nm_id",
        "seller_article",
        "title",
        "plan_price",
        "current_full_price",
        "current_discount_percent",
        "current_discounted_price",
        "wb_upload_discount_percent",
        "wb_status",
        "already_participating",
        "status",
        "message",
        "raw_payload",
    }
    assert expected_row_cols.issubset(
        row_cols
    ), f"File import row model missing: {expected_row_cols - row_cols}"


def test_file_import_tables_in_migrations() -> None:
    """Migration chain must create wb_auto_promo_file_imports and rows tables."""
    import pathlib

    migration_dir = pathlib.Path("migrations/versions")
    migration_sources = []
    for f in sorted(migration_dir.glob("*.py")):
        if f.name.startswith("__"):
            continue
        migration_sources.append(f.read_text())

    all_migration_text = "\n".join(migration_sources)
    assert "wb_auto_promo_file_imports" in all_migration_text
    assert "wb_auto_promo_file_import_rows" in all_migration_text


def test_latest_auto_promo_import_migration_creates_tables() -> None:
    """Latest drift-repair migration must create import and row tables."""
    from importlib import import_module

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = import_module("migrations.versions.20260525_0046_wb_auto_promo_imports")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table(
        "marketplace_accounts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert "wb_auto_promo_file_imports" in tables
        assert "wb_auto_promo_file_import_rows" in tables

        import_columns = {
            column["name"] for column in inspector.get_columns("wb_auto_promo_file_imports")
        }
        assert {
            "id",
            "user_id",
            "marketplace_account_id",
            "original_file_name",
            "promotion_name",
            "status",
            "total_rows",
            "valid_rows",
            "error_rows",
            "warning_rows",
            "applied_at",
            "error_text",
            "created_at",
            "updated_at",
        }.issubset(import_columns)

        row_columns = {
            column["name"] for column in inspector.get_columns("wb_auto_promo_file_import_rows")
        }
        assert {"id", "import_id", "row_number", "wb_nm_id", "status"}.issubset(row_columns)

        index_names = {
            index["name"] for index in inspector.get_indexes("wb_auto_promo_file_imports")
        }
        assert "ix_wb_auto_promo_file_imports_user_id" in index_names
        assert "ix_wb_auto_promo_file_imports_marketplace_account_id" in index_names
        assert "ix_wb_auto_promo_file_imports_status" in index_names
        assert "ix_wb_auto_promo_file_imports_created_at" in index_names


def test_wb_full_price_multiplier_is_4() -> None:
    """WB full price multiplier must be 4 (75% discount)."""
    from app.models.domain import MrcPricingSettings

    multiplier_col = None
    for col in MrcPricingSettings.__table__.columns:
        if col.key == "full_price_multiplier":
            multiplier_col = col
            break
    assert multiplier_col is not None
    assert multiplier_col.default.arg == Decimal("4.00")


def test_pricing_routes_all_have_safe_return_types() -> None:
    """All pricing route handlers must have safe return type annotations."""
    import inspect

    from app.web.route_modules.pricing import router

    for route in router.routes:
        if not hasattr(route, "endpoint"):
            continue
        endpoint = route.endpoint
        sig = inspect.signature(endpoint)
        return_annotation = sig.return_annotation
        if return_annotation is inspect.Signature.empty:
            continue
        annotation_str = str(return_annotation)
        assert (
            "|" not in annotation_str or "None" in annotation_str
        ), f"Route {route.path} has unsafe union return type: {annotation_str}"
