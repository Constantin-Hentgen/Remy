"""Shared fixtures: an app on a temporary SQLite database, with a frozen clock and synthetic users."""

import datetime

import pytest
from fastapi.testclient import TestClient

from remy.service.app import create_app
from remy.service.settings import Settings

ADMIN_KEY = "test-admin-key"
NOW_UTC = datetime.datetime(2026, 11, 14, 13, 0, tzinfo=datetime.UTC)  # 14:00 in Paris: lunch slot
TODAY = "2026-11-14"


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'remy.db'}",
        remy_admin_key=ADMIN_KEY,
        remy_off_enabled=False,
        _env_file=None,
    )
    app = create_app(settings)
    app.state.clock = lambda: NOW_UTC
    yield app
    app.state.engine.dispose()


@pytest.fixture
def anon(app):
    return TestClient(app)


@pytest.fixture
def admin(app):
    return TestClient(app, headers={"Authorization": f"Bearer {ADMIN_KEY}"})


def make_user(admin: TestClient, app, name: str, **body) -> TestClient:
    created = admin.post("/v1/admin/users", json={"name": name, **body})
    assert created.status_code == 201, created.text
    return TestClient(app, headers={"Authorization": f"Bearer {created.json()['api_key']['key']}"})


@pytest.fixture
def alice(admin, app):
    """A synthetic athlete in Paris with a complete profile (BMR 1667.5 kcal)."""
    client = make_user(admin, app, "alice")
    r = client.put("/v1/me/profile", json={"weight_kg": 70, "height_cm": 178, "birth_year": 1996, "sex": "male"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def bruno(admin, app):
    return make_user(admin, app, "bruno", timezone="America/New_York", lang="en")
