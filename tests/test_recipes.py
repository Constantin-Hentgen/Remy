"""Recipes as foods, on synthetic dishes."""

import pytest
from fastapi.testclient import TestClient

from remy.client import RemyClient
from tests.conftest import make_user

RICE_CHICKEN = {
    "name": "  Riz   poulet ",
    "portions": 2,
    "external_id": "groceries:rc",
    "items": [{"food_query": "riz blanc cuit", "grams": 400}, {"food_query": "blanc de poulet", "grams": 200}],
}


@pytest.fixture
def alice(app, admin):
    return make_user(admin, app, "alice")


def test_create_and_read(alice):
    r = alice.post("/v1/me/recipes", json=RICE_CHICKEN)
    assert r.status_code == 201, r.text
    saved = r.json()
    recipe = saved["recipe"]
    assert saved["created"] and saved["warnings"] == []
    assert recipe["name"] == "Riz poulet" and recipe["code"] == f"recipe:{recipe['id']}" and recipe["portions"] == 2
    assert recipe["weight_g"] == 600 and recipe["portion_g"] == 300 and len(recipe["items"]) == 2
    kcal = recipe["totals"]["kcal"]
    assert kcal > 0 and recipe["per_portion"]["kcal"] == pytest.approx(kcal / 2, abs=0.1)
    assert recipe["per_100g"]["kcal"] == pytest.approx(kcal / 6, abs=0.1)
    assert alice.get(f"/v1/me/recipes/{recipe['id']}").json() == recipe
    assert alice.get("/v1/me/recipes").json() == [recipe]
    assert alice.get("/v1/me/recipes", params={"external_id": "groceries:rc"}).json() == [recipe]
    assert alice.get("/v1/me/recipes", params={"external_id": "nope"}).json() == []


def test_yield_changes_the_density_not_the_totals(alice):
    plain = alice.post("/v1/me/recipes", json={**RICE_CHICKEN, "external_id": None}).json()["recipe"]
    dry = alice.post("/v1/me/recipes", json={**RICE_CHICKEN, "external_id": None, "yield_g": 450}).json()["recipe"]
    assert dry["totals"] == plain["totals"] and dry["weight_g"] == 450 and dry["portion_g"] == 225
    assert dry["per_100g"]["kcal"] > plain["per_100g"]["kcal"]
    assert dry["per_portion"] == plain["per_portion"]


def test_logging_by_portion_and_by_gram(alice):
    recipe = alice.post("/v1/me/recipes", json=RICE_CHICKEN).json()["recipe"]
    code = recipe["code"]
    one = alice.post("/v1/me/meals", json={"text": "riz poulet", "items": [{"food_code": code, "portions": 1}]}).json()
    assert one["warnings"] == [] and one["meal"]["items"][0]["grams"] == 300
    assert one["meal"]["nutrients"]["kcal"] == pytest.approx(recipe["per_portion"]["kcal"], abs=1)
    assert one["meal"]["items"][0]["food_name"] == "Riz poulet"
    half = alice.post("/v1/nutrients", json={"items": [{"food_code": code, "portions": 0.5}]}).json()
    assert half["items"][0]["grams"] == 150 and half["totals"]["kcal"] == pytest.approx(
        recipe["per_portion"]["kcal"] / 2, abs=1
    )
    grams = alice.post("/v1/nutrients", json={"items": [{"food_code": code, "grams": 300}]}).json()
    assert grams["totals"]["kcal"] == one["meal"]["nutrients"]["kcal"]


def test_portions_need_a_food_with_a_portion_size(alice):
    r = alice.post("/v1/nutrients", json={"items": [{"food_query": "riz blanc cuit", "portions": 1}]}).json()
    assert r["items"] == [] and [w["code"] for w in r["warnings"]] == ["no_portion"]
    assert alice.post("/v1/nutrients", json={"items": [{"food_query": "riz", "portions": 0}]}).status_code == 422


def test_history_is_stable(alice):
    recipe = alice.post("/v1/me/recipes", json=RICE_CHICKEN).json()["recipe"]
    meal = alice.post(
        "/v1/me/meals", json={"text": "riz poulet", "items": [{"food_code": recipe["code"], "portions": 1}]}
    ).json()["meal"]
    changed = alice.put(
        f"/v1/me/recipes/{recipe['id']}", json={**RICE_CHICKEN, "items": [{"food_query": "pâtes cuites", "grams": 100}]}
    )
    assert changed.status_code == 200 and not changed.json()["created"]
    assert alice.get(f"/v1/me/meals/{meal['id']}").json()["nutrients"] == meal["nutrients"]
    assert alice.delete(f"/v1/me/recipes/{recipe['id']}").json()["id"] == recipe["id"]
    assert alice.get(f"/v1/me/meals/{meal['id']}").json()["nutrients"] == meal["nutrients"]
    assert alice.get(f"/v1/me/recipes/{recipe['id']}").status_code == 404
    gone = alice.post("/v1/nutrients", json={"items": [{"food_code": recipe["code"], "portions": 1}]}).json()
    assert [w["code"] for w in gone["warnings"]] == ["unknown_food_code"]


def test_external_id_replaces_and_conflicts(alice):
    first = alice.post("/v1/me/recipes", json=RICE_CHICKEN).json()["recipe"]
    again = alice.post("/v1/me/recipes", json={**RICE_CHICKEN, "name": "Riz poulet v2", "portions": 4})
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["recipe"]["id"] == first["id"] and again.json()["recipe"]["name"] == "Riz poulet v2"
    assert len(alice.get("/v1/me/recipes").json()) == 1
    other = alice.post("/v1/me/recipes", json={**RICE_CHICKEN, "external_id": "groceries:other"}).json()["recipe"]
    clash = alice.put(f"/v1/me/recipes/{other['id']}", json=RICE_CHICKEN)
    assert clash.status_code == 409


def test_unmatched_ingredients_warn_and_empty_recipes_are_refused(alice):
    body = {
        **RICE_CHICKEN,
        "external_id": None,
        "items": [{"food_query": "riz blanc cuit", "grams": 200}, {"food_query": "zzzz", "grams": 50}],
    }
    saved = alice.post("/v1/me/recipes", json=body).json()
    assert [w["code"] for w in saved["warnings"]] == ["no_match"] and len(saved["recipe"]["items"]) == 1
    empty = alice.post("/v1/me/recipes", json={**body, "items": [{"food_query": "zzzz", "grams": 50}]})
    assert empty.status_code == 422 and "no ingredient" in empty.json()["detail"]
    assert alice.post("/v1/me/recipes", json={**body, "items": []}).status_code == 422
    assert alice.post("/v1/me/recipes", json={**body, "portions": 0}).status_code == 422


def test_a_recipe_cannot_contain_a_recipe(alice):
    inner = alice.post("/v1/me/recipes", json=RICE_CHICKEN).json()["recipe"]
    body = {
        "name": "outer",
        "items": [{"food_code": inner["code"], "grams": 100}, {"food_query": "riz blanc cuit", "grams": 100}],
    }
    saved = alice.post("/v1/me/recipes", json=body).json()
    assert [w["code"] for w in saved["warnings"]] == ["unknown_food_code"] and len(saved["recipe"]["items"]) == 1


def test_recipes_are_private(app, admin, alice):
    bruno = make_user(admin, app, "bruno")
    recipe = alice.post("/v1/me/recipes", json=RICE_CHICKEN).json()["recipe"]
    assert bruno.get("/v1/me/recipes").json() == []
    assert bruno.get(f"/v1/me/recipes/{recipe['id']}").status_code == 404
    assert bruno.delete(f"/v1/me/recipes/{recipe['id']}").status_code == 404
    assert bruno.put(f"/v1/me/recipes/{recipe['id']}", json=RICE_CHICKEN).status_code == 404
    stolen = bruno.post("/v1/nutrients", json={"items": [{"food_code": recipe["code"], "portions": 1}]}).json()
    assert stolen["items"] == [] and stolen["warnings"][0]["code"] == "unknown_food_code"
    assert bruno.get("/v1/foods", params={"q": "poulet", "source": "recipe"}).json()["foods"] == []
    assert bruno.post("/v1/me/recipes", json=RICE_CHICKEN).status_code == 201  # same external_id, other user
    assert TestClient(app).get("/v1/me/recipes").status_code == 401


def test_search_finds_own_recipes(alice):
    alice.post("/v1/me/recipes", json=RICE_CHICKEN)
    only = alice.get("/v1/foods", params={"q": "riz poulet", "source": "recipe"}).json()["foods"]
    assert [f["source"] for f in only] == ["recipe"] and only[0]["portion_g"] == 300 and only[0]["name"] == "Riz poulet"
    assert "recipe" not in {f["source"] for f in alice.get("/v1/foods", params={"q": "riz poulet"}).json()["foods"]}
    best = alice.get("/v1/foods", params={"q": "riz poulet", "source": "all"}).json()["foods"][0]
    assert best["source"] == "recipe"


def test_client_methods(app, admin):
    key = admin.post("/v1/admin/users", json={"name": "carol"}).json()["api_key"]["key"]
    with RemyClient(api_key=key, http=TestClient(app)) as remy:
        saved = remy.save_recipe(
            "Riz poulet", [{"food_query": "riz blanc cuit", "grams": 300}], portions=2, external_id="x"
        )
        assert saved.created and remy.recipes()[0].code == saved.recipe.code
        assert remy.recipe(saved.recipe.id).name == "Riz poulet"
        logged = remy.log_meal("riz", items=[{"food_code": saved.recipe.code, "portions": 1}])
        assert logged.meal.items[0].grams == 150
        assert (
            remy.save_recipe("Riz", [{"food_query": "riz blanc cuit", "grams": 100}], external_id="x").created is False
        )
        assert remy.delete_recipe(saved.recipe.id).id == saved.recipe.id
