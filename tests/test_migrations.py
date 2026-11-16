"""Migrations run up from an empty database and produce exactly the tables the models describe."""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from remy.service import migrate
from remy.service.db import Base, make_engine


def test_upgrade_from_empty_matches_the_models(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'nested' / 'remy.db'}")  # the folder is created
    migrate.upgrade(engine)
    tables = set(sa.inspect(engine).get_table_names())
    assert tables == {"alembic_version", "users", "api_keys", "meals", "workouts", "slot_checks", "off_products"}
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []
    engine.dispose()


def test_upgrade_is_idempotent_and_keeps_data(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'remy.db'}")
    migrate.upgrade(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (name, timezone, lang, goals, created_at) "
            "VALUES ('synthetic', 'Europe/Paris', 'fr', '{}', '2026-01-01 00:00:00')"
        )
    migrate.upgrade(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT name FROM users").scalar() == "synthetic"
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0002"
    engine.dispose()


def test_foreign_keys_are_enforced_on_sqlite(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'remy.db'}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_in_memory_database_keeps_one_connection():
    engine = make_engine("sqlite://")
    migrate.upgrade(engine)
    assert "users" in sa.inspect(engine).get_table_names()
    engine.dispose()
