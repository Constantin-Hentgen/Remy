"""Initial schema: users, API keys, meals, workouts, slot checks.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None

NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g", "sugars_g", "fiber_g", "salt_g")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("weight_kg", sa.Double(), nullable=True),
        sa.Column("height_cm", sa.Double(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(8), nullable=True),
        sa.Column("activity_factor", sa.Double(), nullable=True),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("name", name="uq_users_name"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_api_keys_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_table(
        "meals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        *(sa.Column(n, sa.Double(), nullable=True) for n in NUTRIENTS),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("repeat", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_meals_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_meals"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_meals_user_id"),
    )
    op.create_index("ix_meals_user_id_date", "meals", ["user_id", "date"])
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("kcal", sa.Double(), nullable=True),
        sa.Column("km", sa.Double(), nullable=True),
        sa.Column("minutes", sa.Double(), nullable=True),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_workouts_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workouts"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_workouts_user_id"),
    )
    op.create_index("ix_workouts_user_id_date", "workouts", ["user_id", "date"])
    op.create_table(
        "slot_checks",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_slot_checks_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "date", "slot", name="pk_slot_checks"),
    )


def downgrade() -> None:
    op.drop_table("slot_checks")
    op.drop_index("ix_workouts_user_id_date", table_name="workouts")
    op.drop_table("workouts")
    op.drop_index("ix_meals_user_id_date", table_name="meals")
    op.drop_table("meals")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
