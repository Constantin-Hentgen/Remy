"""Open Food Facts product cache.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "off_products",
        sa.Column("barcode", sa.String(14), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("name_fr", sa.String(300), nullable=True),
        sa.Column("name_en", sa.String(300), nullable=True),
        sa.Column("brand", sa.String(200), nullable=True),
        *[
            sa.Column(n, sa.Double(), nullable=True)
            for n in ("kcal", "protein_g", "carbs_g", "fat_g", "sugars_g", "fiber_g", "salt_g")
        ],
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("barcode", name=op.f("pk_off_products")),
    )


def downgrade() -> None:
    op.drop_table("off_products")
