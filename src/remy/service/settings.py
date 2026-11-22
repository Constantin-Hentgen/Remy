"""Service configuration, read from environment variables (documented in ``.env.example`` and the wiki)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Empty variables count as unset: Portainer and ``docker compose`` interpolation pass ``VAR=`` for anything the
    operator left blank, and that must fall back to the default rather than fail validation.
    """

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    remy_api_key: SecretStr | None = Field(
        default=None,
        description="Bearer key every /v1 call must send. Unset: /v1 refuses every call (401).",
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        description="Anthropic API key for recipe suggestions. Unset: POST /v1/suggest answers 503.",
    )
    remy_model: str = Field(default="claude-opus-5-5", description="Claude model that drafts the recipes.")
    log_level: str = Field(default="INFO", description="Python logging level: DEBUG, INFO, WARNING, ERROR.")


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; tests clear the cache to change them."""
    return Settings()
