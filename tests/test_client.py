"""The typed client, run against the app in-process (the TestClient is an httpx.Client)."""

import pytest
from fastapi.testclient import TestClient

from remy.client import RemyClient, RemyError
from tests.conftest import API_KEY


@pytest.fixture
def remy(app):
    with RemyClient(api_key=API_KEY, http=TestClient(app)) as client:
        yield client


def test_foods_and_nutrients(remy):
    found = remy.foods("riz blanc cuit", limit=2)
    assert found.foods[0].code == "9104" and found.lang == "fr" and len(found.foods) == 2
    assert remy.foods("rice", lang="en").foods[0].name.startswith("Rice")
    out = remy.nutrients([{"food_code": "9104", "grams": 200}, {"food_query": "blanc de poulet", "grams": 150}])
    assert out.totals.kcal > 0 and len(out.items) == 2 and out.warnings == []


def test_errors_raise(app):
    with RemyClient(api_key="wrong", http=TestClient(app)) as client, pytest.raises(RemyError) as e:
        client.foods("riz")
    assert e.value.status_code == 401
