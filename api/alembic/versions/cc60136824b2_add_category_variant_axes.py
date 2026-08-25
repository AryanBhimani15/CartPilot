"""add category variant axes

Revision ID: cc60136824b2
Revises: 1cb4ff4ac995
Create Date: 2026-08-25 08:57:07.331636

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'cc60136824b2'
down_revision = '1cb4ff4ac995'
branch_labels = None
depends_on = None

variant_axis = postgresql.ENUM(
    "footwear_size",
    "apparel_size",
    "one_size",
    name="variant_axis",
    create_type=False,
)


def upgrade() -> None:
    variant_axis.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "product_variants",
        sa.Column("axis", variant_axis, nullable=False, server_default="footwear_size"),
    )
    op.alter_column("product_variants", "axis", server_default=None)


def downgrade() -> None:
    op.drop_column("product_variants", "axis")
    variant_axis.drop(op.get_bind(), checkfirst=True)
