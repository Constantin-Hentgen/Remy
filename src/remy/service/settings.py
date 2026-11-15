"""Service configuration, read from environment variables (documented in ``.env.example`` and the wiki)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting has a safe default so that ``docker compose up`` works on a fresh machine.

    Empty variables count as unset: Portainer and ``docker compose`` interpolation pass ``VAR=`` for anything the
    operator left blank, and that must fall back to the default rather than fail validation.
    """

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    database_url: str = Field(
        default="sqlite:///./data/remy.db",
        description="SQLAlchemy URL. SQLite file by default; a postgresql+psycopg:// URL also works.",
    )
    remy_admin_key: SecretStr | None = Field(
        default=None,
        description="Bearer key with admin rights (creating users and their API keys). Unset: no admin access.",
    )
    log_level: str = Field(default="INFO", description="Python logging level: DEBUG, INFO, WARNING, ERROR.")


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; tests clear the cache to change them."""
    return Settings()
