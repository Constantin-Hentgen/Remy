"""Service skeleton: health probe, configuration and request logging."""

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from remy import __version__
from remy.service.app import create_app
from remy.service.settings import Settings, get_settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    return TestClient(create_app(Settings(database_url="sqlite://", _env_file=None)))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__, "database": "ok"}


def test_openapi_is_served(client):
    assert client.get("/openapi.json").json()["info"]["title"] == "Remy"


def test_requests_are_logged_without_query_string(client, caplog):
    with caplog.at_level(logging.INFO, logger="remy"):
        client.get("/health?weight=72")
    ours = [r.getMessage() for r in caplog.records if r.name == "remy"]
    assert any("GET /health -> 200" in m for m in ours)
    assert not any("weight" in m for m in ours)


def test_uvicorn_access_log_is_disabled():
    # uvicorn's access log prints query strings, which can carry health data; the middleware logs instead.
    assert 'CMD ["remy", "serve"]' in (ROOT / "Dockerfile").read_text()
    assert "access_log=False" in (ROOT / "src" / "remy" / "cli.py").read_text()


def test_empty_env_vars_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("LOG_LEVEL", "")
    s = Settings(_env_file=None)
    assert s.database_url == Settings.model_fields["database_url"].default
    assert s.log_level == "INFO"


def test_env_vars_are_read(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db/remy")
    monkeypatch.setenv("REMY_ADMIN_KEY", "s3cret")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.database_url.startswith("postgresql")
        assert s.remy_admin_key.get_secret_value() == "s3cret"
        assert "s3cret" not in repr(s)
    finally:
        get_settings.cache_clear()


def test_env_example_documents_every_setting():
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert {name.upper() for name in Settings.model_fields} <= documented


def test_compose_passes_every_setting():
    compose = (ROOT / "docker-compose.yml").read_text()
    for name in Settings.model_fields:
        assert f"{name.upper()}:" in compose
