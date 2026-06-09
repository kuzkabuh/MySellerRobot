"""Add operation_category to financial_report_rows for classified operation grouping.

Revision ID: 20260609_0062
Revises: 20260608_0061
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0062"
down_revision: str | None = "20260608_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def classify_operation_type(doc_type_name: str | None, operation_name: str | None) -> str | None:
    """Lightweight inline classifier for migration backfill.

    Mirrors app/services/wb/reports/operation_classifier.py logic
    without importing the module (avoids env dependency issues).
    """
    text = (operation_name or doc_type_name or "").strip().lower()
    if not text:
        return None
    if any(kw in text for kw in ("возврат", "return")):
        return "return"
    if any(kw in text for kw in ("логист", "достав", "delivery", "logistic")):
        return "logistics"
    if any(kw in text for kw in ("хранен", "storage", "хран")):
        return "storage"
    if any(kw in text for kw in ("приемк", "приёмк", "acceptance", "приём")):
        return "paid_acceptance"
    if any(kw in text for kw in ("штраф", "penalty", "fine")):
        return "penalty"
    if any(kw in text for kw in ("удержан", "deduction", "удержание")):
        return "deduction"
    if any(kw in text for kw in ("компенсац", "возмещ", "compensation", "доплат", "additional")):
        return "compensation"
    if any(kw in text for kw in ("коррект", "adjustment", "correction")):
        return "adjustment"
    if any(kw in text for kw in ("эквайринг", "acquiring", "payment processing")):
        return "acquiring"
    if any(kw in text for kw in ("комисс", "commission", "reward", "вознаграж")):
        return "commission"
    if any(kw in text for kw in ("продаж", "реализац", "sale")):
        return "sale"
    return None


def upgrade() -> None:
    op.add_column(
        "financial_report_rows",
        sa.Column("operation_category", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_financial_report_rows_operation_category",
        "financial_report_rows",
        ["operation_category"],
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, operation_type, raw_payload::text FROM financial_report_rows "
            "WHERE operation_category IS NULL"
        )
    ).fetchall()

    updated = 0
    for row_id, operation_type, raw_json in rows:
        import json

        try:
            payload = json.loads(raw_json) if raw_json else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}

        doc_type = payload.get("docTypeName") or payload.get("doc_type_name")
        seller_oper = payload.get("sellerOperName") or payload.get("seller_oper_name")
        category = classify_operation_type(
            doc_type_name=str(doc_type) if doc_type else None,
            operation_name=str(seller_oper) if seller_oper else operation_type,
        )
        if category:
            connection.execute(
                sa.text(
                    "UPDATE financial_report_rows SET operation_category = :cat WHERE id = :id"
                ),
                {"cat": category, "id": row_id},
            )
            updated += 1

    if updated:
        op.execute(
            sa.text(
                "UPDATE financial_report_rows "
                "SET operation_category = 'other' "
                "WHERE operation_category IS NULL AND operation_type IS NOT NULL"
            )
        )


def downgrade() -> None:
    op.drop_index("ix_financial_report_rows_operation_category", table_name="financial_report_rows")
    op.drop_column("financial_report_rows", "operation_category")
