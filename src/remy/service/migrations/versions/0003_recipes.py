"""Recipes.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("portions", sa.Double(), nullable=False),
        sa.Column("yield_g", sa.Double(), nullable=True),
        sa.Column("ingredients", sa.JSON(), nullable=False),
        *[
            sa.Column(n, sa.Double(), nullable=True)
            for n in ("kcal", "protein_g", "carbs_g", "fat_g", "sugars_g", "fiber_g", "salt_g")
        ],
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_recipes_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipes")),
        sa.UniqueConstraint("user_id", "external_id", name=op.f("uq_recipes_user_id")),
    )
    op.create_index("ix_recipes_user_id", "recipes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_recipes_user_id", table_name="recipes")
    op.drop_table("recipes")
