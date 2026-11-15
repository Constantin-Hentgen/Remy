"""Database tables (SQLAlchemy 2) and engine setup.

Meals are stored with the user's *local* date and time, because that is how people think about food ("lunch on the
14th") and what the daily rules use; the time zone lives on the user.
"""

import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    MetaData,
    String,
    Time,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.pool import StaticPool


def utcnow() -> datetime.datetime:
    """Naive UTC: SQLite drops offsets, so every stored timestamp is UTC by convention."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    # Explicit constraint names keep migrations identical on SQLite and Postgres.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    timezone: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(2))
    weight_kg: Mapped[float | None]
    height_cm: Mapped[float | None]
    birth_year: Mapped[int | None]
    sex: Mapped[str | None] = mapped_column(String(8))
    activity_factor: Mapped[float | None]
    goals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="api_keys")


class MealRow(Base):
    __tablename__ = "meals"
    __table_args__ = (
        UniqueConstraint("user_id", "external_id"),
        Index("ix_meals_user_id_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[datetime.date] = mapped_column(Date)
    time: Mapped[datetime.time] = mapped_column(Time)
    slot: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(200))
    kcal: Mapped[float | None]
    protein_g: Mapped[float | None]
    carbs_g: Mapped[float | None]
    fat_g: Mapped[float | None]
    sugars_g: Mapped[float | None]
    fiber_g: Mapped[float | None]
    salt_g: Mapped[float | None]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40), default="api")
    repeat: Mapped[bool] = mapped_column(default=False)
    skipped: Mapped[bool] = mapped_column(default=False)
    external_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class WorkoutRow(Base):
    __tablename__ = "workouts"
    __table_args__ = (
        UniqueConstraint("user_id", "external_id"),
        Index("ix_workouts_user_id_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[datetime.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(40), default="run")
    kcal: Mapped[float | None]
    km: Mapped[float | None]
    minutes: Mapped[float | None]
    external_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class SlotCheckRow(Base):
    __tablename__ = "slot_checks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    slot: Mapped[str] = mapped_column(String(16), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


def make_engine(database_url: str) -> Engine:
    """Engine for the configured URL. SQLite gets its folder created, foreign keys on and cross-thread access
    (FastAPI runs sync endpoints in a thread pool); an in-memory SQLite database keeps a single connection."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if url.database in (None, "", ":memory:"):
        kwargs["poolclass"] = StaticPool
    else:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
