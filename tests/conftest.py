"""Shared fixtures: the stateless app with a known API key."""

import pytest
from fastapi.testclient import TestClient

from remy.service.app import create_app
from remy.service.settings import Settings

API_KEY = "test-api-key"


@pytest.fixture
def settings():
    return Settings(remy_api_key=API_KEY, _env_file=None)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def anon(app):
    return TestClient(app)


@pytest.fixture
def api(app):
    return TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"})
