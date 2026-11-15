"""Run the Alembic migrations shipped in the package."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["engine"] = engine
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Bring the database to ``revision`` (creates the tables on an empty database)."""
    command.upgrade(alembic_config(engine), revision)
