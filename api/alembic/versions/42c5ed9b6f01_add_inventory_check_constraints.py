"""add inventory check constraints

Revision ID: 42c5ed9b6f01
Revises: cc60136824b2
Create Date: 2026-08-25 12:00:00.000000
"""

from alembic import op

revision = "42c5ed9b6f01"
down_revision = "cc60136824b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_product_variants_stock_nonnegative", "product_variants", "stock_qty >= 0"
    )
    op.create_check_constraint(
        "ck_product_variants_reserved_within_stock",
        "product_variants",
        "reserved_qty >= 0 AND reserved_qty <= stock_qty",
    )


def downgrade() -> None:
    op.drop_constraint("ck_product_variants_reserved_within_stock", "product_variants")
    op.drop_constraint("ck_product_variants_stock_nonnegative", "product_variants")
