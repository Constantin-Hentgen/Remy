"""Alembic environment. The engine is passed in by :mod:`remy.service.migrate` (no alembic.ini)."""

from alembic import context

from remy.service.db import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = context.config.attributes["engine"]
    with engine.connect() as connection:
        # render_as_batch: SQLite cannot ALTER most things in place.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
