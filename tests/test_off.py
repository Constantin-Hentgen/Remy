"""Open Food Facts: parsing, the cache, the endpoints. No test touches the network: OFF is a fake transport."""

import httpx
import pytest

from remy import off
from remy.foods import Food, FoodTable, Nutrients
from remy.nutrients import FoodUnavailable, compute
from remy.service import openfoodfacts
from remy.service.openfoodfacts import USER_AGENT, OpenFoodFacts
from remy.service.settings import Settings
from tests.conftest import make_user

BAR = "3000000000017"  # synthetic
PRODUCT = {
    "code": BAR,
    "product_name": "Chocolate spread",
    "product_name_fr": "Pâte à tartiner chocolat",
    "brands": "Acme, Acme Foods",
    "nutriments": {
        "energy-kcal_100g": 540,
        "proteins_100g": 6.1,
        "carbohydrates_100g": "57.5",
        "fat_100g": 31,
        "sugars_100g": 56,
        "salt_100g": 0.1,
    },
}


def payload(product=PRODUCT, status=1):
    return {"status": status, "code": BAR, "product": product}


# --- parsing ------------------------------------------------------------------------------------------------------


def test_parse_product():
    food = off.parse_product(BAR, PRODUCT)
    assert food.code == f"off:{BAR}" and food.source == "off" and food.brand == "Acme"
    assert food.name_fr == "Pâte à tartiner chocolat" and food.name("en") == "Pâte à tartiner chocolat"
    assert food.per_100g == Nutrients(kcal=540, protein_g=6.1, carbs_g=57.5, fat_g=31, sugars_g=56, salt_g=0.1)
    assert "ODbL" in food.attribution and food.portion_g is None


def test_parse_energy_and_salt_fallbacks():
    n = off.nutrients_of({"energy_100g": 1000, "sodium_100g": 0.4, "proteins_100g": -3, "fat_100g": "x"})
    assert n.kcal == 239 and n.salt_g == 1.0 and n.protein_g is None and n.fat_g is None


def test_a_product_without_energy_is_refused():
    assert off.parse_product(BAR, {"product_name": "x", "nutriments": {"proteins_100g": 3}}) is None
    assert off.parse_product(BAR, {"product_name": "x"}) is None


def test_unnamed_product_gets_a_placeholder_name():
    food = off.parse_product(BAR, {"nutriments": {"energy-kcal_100g": 10}})
    assert food.name_fr == f"Product {BAR}" and food.brand is None


def test_barcodes():
    assert off.is_barcode("12345678") and off.is_barcode("1" * 14)
    assert not any(off.is_barcode(x) for x in ("1234567", "1" * 15, "12a45678", "", "../x"))
    assert off.barcode_of(f"off:{BAR}") == BAR and off.barcode_of("9104") is None and off.barcode_of("off:abc") is None


# --- service: cache, politeness, failures -------------------------------------------------------------------------


class FakeOff:
    """An OFF server: counts requests, answers from ``products``, can fail."""

    def __init__(self):
        self.products = {BAR: payload()}
        self.requests: list[httpx.Request] = []
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("down")
        barcode = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        if barcode in self.products:
            return httpx.Response(200, json=self.products[barcode])
        return httpx.Response(404, json={"status": 0, "code": barcode})


@pytest.fixture
def fake():
    return FakeOff()


@pytest.fixture
def alice(app, admin, fake):
    app.state.off = OpenFoodFacts(Settings(_env_file=None, remy_off_enabled=True), transport=httpx.MockTransport(fake))
    return make_user(admin, app, "alice")


def test_barcode_lookup_is_cached(alice, fake):
    first = alice.get(f"/v1/foods/barcode/{BAR}")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["code"] == f"off:{BAR}" and body["source"] == "off" and body["brand"] == "Acme"
    assert body["per_100g"]["kcal"] == 540 and "ODbL" in body["attribution"]
    assert alice.get(f"/v1/foods/barcode/{BAR}").json() == body
    assert len(fake.requests) == 1


def test_only_the_barcode_leaves_the_server(alice, fake):
    alice.get(f"/v1/foods/barcode/{BAR}")
    request = fake.requests[0]
    assert request.url.path == f"/api/v2/product/{BAR}.json" and request.url.host == "world.openfoodfacts.org"
    sent = f"{request.url} {dict(request.headers)}".lower()
    assert request.headers["user-agent"] == USER_AGENT and "alice" not in sent and "bearer" not in sent
    assert "authorization" not in request.headers and "@" not in USER_AGENT


def test_unknown_barcode_is_404_and_remembered_for_a_day(alice, fake):
    assert alice.get("/v1/foods/barcode/3999999999999").status_code == 404
    assert alice.get("/v1/foods/barcode/3999999999999").status_code == 404
    assert len(fake.requests) == 1


def test_product_without_energy_is_404(alice, fake):
    fake.products["30000000"] = payload({"product_name": "x", "nutriments": {}})
    assert alice.get("/v1/foods/barcode/30000000").status_code == 404


def test_invalid_barcode_and_authentication(alice, anon, fake):
    assert alice.get("/v1/foods/barcode/abc").status_code == 422
    assert anon.get(f"/v1/foods/barcode/{BAR}").status_code == 401
    assert fake.requests == []


def test_off_down_is_503_and_not_cached(alice, fake):
    fake.fail = True
    assert alice.get(f"/v1/foods/barcode/{BAR}").status_code == 503
    fake.fail = False
    assert alice.get(f"/v1/foods/barcode/{BAR}").status_code == 200


def test_stale_cache_is_served_when_off_is_down(alice, app, fake):
    from sqlalchemy.orm import Session

    from remy.service.db import OffProduct, utcnow

    assert alice.get(f"/v1/foods/barcode/{BAR}").status_code == 200
    with Session(app.state.engine) as db:
        row = db.get(OffProduct, BAR)
        row.fetched_at = utcnow().replace(year=2020)
        db.commit()
    fake.fail = True
    assert alice.get(f"/v1/foods/barcode/{BAR}").json()["name"] == "Pâte à tartiner chocolat"
    fake.fail = False
    assert alice.get(f"/v1/foods/barcode/{BAR}").status_code == 200 and len(fake.requests) == 3


def test_disabled_makes_no_request(app, admin, fake):
    app.state.off = OpenFoodFacts(Settings(_env_file=None, remy_off_enabled=False), transport=httpx.MockTransport(fake))
    user = make_user(admin, app, "bruno")
    r = user.get(f"/v1/foods/barcode/{BAR}")
    assert r.status_code == 503 and "disabled" in r.json()["detail"] and fake.requests == []


def test_rate_limit(app, admin, fake, monkeypatch):
    monkeypatch.setattr(openfoodfacts, "MAX_PER_MINUTE", 2)
    app.state.off = OpenFoodFacts(Settings(_env_file=None, remy_off_enabled=True), transport=httpx.MockTransport(fake))
    user = make_user(admin, app, "carol")
    for n in range(2):
        assert user.get(f"/v1/foods/barcode/3{n:07d}").status_code == 404
    limited = user.get("/v1/foods/barcode/30000009")
    assert limited.status_code == 503 and "too many" in limited.json()["detail"] and len(fake.requests) == 2


# --- search and meals ---------------------------------------------------------------------------------------------


def test_search_by_source(alice):
    alice.get(f"/v1/foods/barcode/{BAR}")
    default = alice.get("/v1/foods", params={"q": "tartiner chocolat", "limit": 25}).json()["foods"]
    assert {f["source"] for f in default} == {"ciqual"}
    off_only = alice.get("/v1/foods", params={"q": "tartiner chocolat", "source": "off"}).json()["foods"]
    assert [f["code"] for f in off_only] == [f"off:{BAR}"]
    by_brand = alice.get("/v1/foods", params={"q": "acme", "source": "all"}).json()["foods"]
    assert [f["code"] for f in by_brand] == [f"off:{BAR}"]
    mixed = alice.get("/v1/foods", params={"q": "chocolat", "source": "all", "limit": 25}).json()["foods"]
    assert {f["source"] for f in mixed} == {"ciqual", "off"}
    assert alice.get("/v1/foods", params={"q": "x", "source": "nope"}).status_code == 422


def test_meal_with_an_off_product(alice, fake):
    r = alice.post(
        "/v1/me/meals",
        json={
            "text": "tartines",
            "items": [{"food_code": f"off:{BAR}", "grams": 20}, {"food_query": "pain", "grams": 60}],
        },
    )
    assert r.status_code == 201, r.text
    meal = r.json()["meal"]
    assert meal["items"][0]["food_name"] == "Pâte à tartiner chocolat" and meal["items"][0]["nutrients"]["kcal"] == 108
    assert meal["nutrients"]["kcal"] > 108 and r.json()["warnings"] == []
    again = alice.post("/v1/nutrients", json={"items": [{"food_code": f"off:{BAR}", "grams": 100}]}).json()
    assert again["totals"]["kcal"] == 540 and len(fake.requests) == 1  # second use comes from the cache


def test_unavailable_off_is_a_warning_not_an_error(app, admin, fake):
    app.state.off = OpenFoodFacts(Settings(_env_file=None, remy_off_enabled=False), transport=httpx.MockTransport(fake))
    user = make_user(admin, app, "dora")
    r = user.post(
        "/v1/nutrients",
        json={"items": [{"food_code": f"off:{BAR}", "grams": 100}, {"food_query": "riz", "grams": 100}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert [w["code"] for w in body["warnings"]] == ["source_unavailable"] and len(body["items"]) == 1


def test_unknown_off_code_warns(alice):
    body = alice.post("/v1/nutrients", json={"items": [{"food_code": "off:3999999999999", "grams": 50}]}).json()
    assert [w["code"] for w in body["warnings"]] == ["unknown_food_code"]


# --- library: resolver and portions -------------------------------------------------------------------------------


def test_compute_with_a_resolver_and_portions():
    dish = Food(code="x:1", name_fr="Plat", source="recipe", per_100g=Nutrients(kcal=200), portion_g=300)
    plain = Food(code="x:2", name_fr="Simple", source="recipe", per_100g=Nutrients(kcal=100))

    def resolver(code):
        if code == "x:3":
            raise FoodUnavailable("offline")
        return {"x:1": dish, "x:2": plain}.get(code)

    result = compute(
        [
            {"food_code": "x:1", "portions": 1.5},
            {"food_code": "x:1", "portions": 2, "grams": 100},
            {"food_code": "x:2", "portions": 1},
            {"food_code": "x:3", "grams": 10},
            {"food_code": "x:4", "grams": 10},
        ],
        table=FoodTable([]),
        resolver=resolver,
    )
    assert [(i.index, i.grams, i.nutrients.kcal) for i in result.items] == [(0, 450, 900), (1, 100, 200)]
    assert [(w.index, w.code) for w in result.warnings] == [
        (2, "no_portion"),
        (3, "source_unavailable"),
        (4, "unknown_food_code"),
    ]


def test_httpx_request_logging_is_silenced(app):
    import logging

    assert logging.getLogger("httpx").level == logging.WARNING


def test_client_barcode_and_source(app, admin, fake):
    from fastapi.testclient import TestClient

    from remy.client import RemyClient, RemyError

    app.state.off = OpenFoodFacts(Settings(_env_file=None, remy_off_enabled=True), transport=httpx.MockTransport(fake))
    key = admin.post("/v1/admin/users", json={"name": "erin"}).json()["api_key"]["key"]
    with RemyClient(api_key=key, http=TestClient(app)) as remy:
        assert remy.barcode(BAR).code == f"off:{BAR}"
        assert [f.code for f in remy.foods("acme", source="off").foods] == [f"off:{BAR}"]
        with pytest.raises(RemyError) as e:
            remy.barcode("3999999999999")
        assert e.value.status_code == 404
