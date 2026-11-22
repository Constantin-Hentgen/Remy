"""Service skeleton: health, authentication, configuration and request logging."""

import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient

from remy import __version__
from remy.service.app import create_app
from remy.service.settings import Settings, get_settings
from tests.conftest import API_KEY

ROOT = Path(__file__).resolve().parent.parent


def test_health_needs_no_key(anon):
    r = anon.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_openapi_is_served(anon):
    assert anon.get("/openapi.json").json()["info"]["title"] == "Remy"


def test_v1_needs_the_key(anon):
    assert anon.get("/v1/foods", params={"q": "riz"}).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert anon.get("/v1/foods", params={"q": "riz"}, headers=wrong).status_code == 401
    ok = {"Authorization": f"Bearer {API_KEY}"}
    assert anon.get("/v1/foods", params={"q": "riz"}, headers=ok).status_code == 200


def test_without_a_configured_key_everything_is_refused():
    client = TestClient(create_app(Settings(_env_file=None)))
    r = client.get("/v1/foods", params={"q": "riz"}, headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401 and "REMY_API_KEY" in r.json()["detail"]
    assert client.get("/health").status_code == 200


def test_requests_are_logged_by_route_without_values(api, caplog):
    with caplog.at_level(logging.INFO, logger="remy"):
        api.get("/v1/foods?q=pates")
        api.get("/health?weight=72")
        api.get("/v1/unknown/3017620422003")
    ours = [r.getMessage() for r in caplog.records if r.name == "remy"]
    assert any("GET /v1/foods -> 200" in m for m in ours)
    assert any("GET /health -> 200" in m for m in ours)
    assert not any("pates" in m or "weight" in m or "3017620422003" in m for m in ours)


def test_uvicorn_access_log_is_disabled():
    # uvicorn's access log prints query strings; the middleware logs instead.
    assert 'CMD ["remy", "serve"]' in (ROOT / "Dockerfile").read_text()
    assert "access_log=False" in (ROOT / "src" / "remy" / "cli.py").read_text()


def test_empty_env_vars_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("REMY_API_KEY", "")
    monkeypatch.setenv("LOG_LEVEL", "")
    s = Settings(_env_file=None)
    assert s.remy_api_key is None and s.log_level == "INFO"


def test_env_vars_are_read_and_secrets_hidden(monkeypatch):
    monkeypatch.setenv("REMY_API_KEY", "s3cret")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.remy_api_key.get_secret_value() == "s3cret"
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


def test_image_is_linked_to_the_repository():
    assert (
        'org.opencontainers.image.source="https://github.com/Constantin-Hentgen/Remy"'
        in (ROOT / "Dockerfile").read_text()
    )
