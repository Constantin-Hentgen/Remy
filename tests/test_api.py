"""HTTP API v1 on a temporary SQLite database. All data is synthetic."""

import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TODAY, make_user

PASTA = {"food_query": "pâtes cuites", "grams": 250}
TUNA = {"food_query": "thon au naturel", "grams": 100}


def log(client, text, at, **body):
    r = client.post("/v1/me/meals", json={"text": text, "at": at, **body})
    assert r.status_code == 201, r.text
    return r.json()


# --- auth and admin -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/foods?q=riz", "/v1/me/profile", "/v1/me/meals", "/v1/me/days/today"])
def test_user_routes_need_a_key(anon, path):
    assert anon.get(path).status_code == 401
    assert anon.get(path, headers={"Authorization": "Bearer remy_wrong"}).status_code == 401


def test_admin_routes_need_the_admin_key(anon, alice):
    assert anon.get("/v1/admin/users").status_code == 401
    assert alice.get("/v1/admin/users").status_code == 403


def test_admin_key_cannot_read_user_data(admin, alice):
    assert admin.get("/v1/me/profile").status_code == 401


def test_no_admin_access_without_configured_key(tmp_path):
    from remy.service.app import create_app
    from remy.service.settings import Settings

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'x.db'}", remy_admin_key=None, _env_file=None))
    assert TestClient(app, headers={"Authorization": "Bearer "}).get("/v1/admin/users").status_code in (401, 403)
    assert TestClient(app, headers={"Authorization": "Bearer x"}).get("/v1/admin/users").status_code == 403
    app.state.engine.dispose()


def test_users_and_keys(admin, app):
    created = admin.post("/v1/admin/users", json={"name": "carla", "timezone": "Europe/Lisbon", "lang": "en"}).json()
    user, key = created["user"], created["api_key"]
    assert key["key"].startswith("remy_") and key["prefix"] == key["key"][:10]
    assert admin.post("/v1/admin/users", json={"name": "carla"}).status_code == 409
    assert admin.post("/v1/admin/users", json={"name": "x", "timezone": "Mars/Olympus"}).status_code == 422
    assert admin.post("/v1/admin/users", json={"name": "bad name"}).status_code == 422
    assert [u["name"] for u in admin.get("/v1/admin/users").json()] == ["carla"]

    second = admin.post(f"/v1/admin/users/{user['id']}/keys", json={"label": "bot"}).json()
    listed = admin.get(f"/v1/admin/users/{user['id']}/keys").json()
    assert [k["label"] for k in listed] == ["", "bot"] and "key" not in listed[0]

    client = TestClient(app, headers={"Authorization": f"Bearer {second['key']}"})
    assert client.get("/v1/me/profile").status_code == 200
    assert admin.post(f"/v1/admin/keys/{second['id']}/revoke").json()["revoked_at"]
    assert client.get("/v1/me/profile").status_code == 401
    assert admin.post("/v1/admin/keys/999/revoke").status_code == 404
    assert admin.post("/v1/admin/users/999/keys").status_code == 404


def test_keys_are_stored_hashed(admin, app):
    key = admin.post("/v1/admin/users", json={"name": "dora"}).json()["api_key"]["key"]
    with app.state.engine.connect() as c:
        stored = c.exec_driver_sql("SELECT key_hash, prefix FROM api_keys").all()
    assert key not in str(stored) and len(stored[0][0]) == 64


# --- foods and nutrients --------------------------------------------------------------------------------------


def test_food_search(alice):
    r = alice.get("/v1/foods", params={"q": "riz blanc cuit", "limit": 3}).json()
    assert r["lang"] == "fr" and len(r["foods"]) == 3
    first = r["foods"][0]
    assert first["code"] == "9104" and first["name"] == "Riz blanc, cuit, non salé" and first["source"] == "ciqual"
    assert first["per_100g"]["kcal"] > 100
    assert alice.get("/v1/foods", params={"q": "xyzzy"}).json()["foods"] == []
    assert alice.get("/v1/foods").status_code == 422
    assert alice.get("/v1/foods", params={"q": "riz", "limit": 100}).status_code == 422


def test_food_search_uses_the_users_language(bruno):
    assert bruno.get("/v1/foods", params={"q": "riz"}).json()["lang"] == "en"
    assert bruno.get("/v1/foods", params={"q": "riz", "lang": "fr"}).json()["lang"] == "fr"


def test_nutrients(alice):
    r = alice.post("/v1/nutrients", json={"items": [PASTA, TUNA, {"food_query": "xyzzy", "grams": 20}]}).json()
    assert r["totals"]["kcal"] == 426 and len(r["items"]) == 2
    assert r["warnings"] == [{"index": 2, "code": "no_match", "label": "xyzzy", "detail": "no matching food"}]


# --- profile --------------------------------------------------------------------------------------------------


def test_profile_put_and_patch(alice):
    p = alice.get("/v1/me/profile").json()
    assert p["bmr_kcal"] == 1667.5 and p["rest_day_needs_kcal"] == 2334.5 and p["missing"] == []
    assert p["timezone"] == "Europe/Paris" and p["lang"] == "fr" and p["sex"] == "male"

    p = alice.patch("/v1/me/profile", json={"weight_kg": 72, "goals": {"target_weight_kg": 68}}).json()
    assert p["weight_kg"] == 72 and p["height_cm"] == 178 and p["goals"]["target_weight_kg"] == 68
    p = alice.patch("/v1/me/profile", json={"goals": {"protein_g_per_kg": 1.6}, "activity_factor": 1.5}).json()
    assert p["goals"] == {"target_weight_kg": 68, "protein_g_per_kg": 1.6} and p["activity_factor"] == 1.5

    p = alice.put("/v1/me/profile", json={"weight_kg": 70, "sex": "femme", "timezone": "Europe/Lisbon"}).json()
    assert p["height_cm"] is None and p["missing"] == ["height_cm", "birth_year"] and p["bmr_kcal"] is None
    assert p["sex"] == "female" and p["timezone"] == "Europe/Lisbon" and p["lang"] == "fr"
    assert p["goals"] == {"target_weight_kg": None, "protein_g_per_kg": None} and p["activity_factor"] is None


@pytest.mark.parametrize(
    "bad", [{"weight_kg": 5}, {"height_cm": 50}, {"birth_year": 1800}, {"sex": "autre"}, {"timezone": "Nowhere/City"}]
)
def test_profile_validation(alice, bad):
    assert alice.patch("/v1/me/profile", json=bad).status_code == 422


# --- meals ----------------------------------------------------------------------------------------------------


def test_log_meal_computes_nutrients(alice):
    out = log(
        alice, "  Pâtes   au thon ", f"{TODAY}T12:30:00", items=[PASTA, TUNA, {"food_query": "xyzzy", "grams": 5}]
    )
    meal = out["meal"]
    assert meal["text"] == "Pâtes au thon" and meal["date"] == TODAY and meal["time"] == "12:30"
    assert meal["slot"] == "lunch" and meal["nutrients"]["kcal"] == 426 and meal["nutrients"]["fat_g"] is not None
    assert [i["grams"] for i in meal["items"]] == [250, 100] and meal["source"] == "api"
    assert out["created"] and out["possible_duplicate"] is None
    assert [w["code"] for w in out["warnings"]] == ["no_match"]
    assert alice.get(f"/v1/me/meals/{meal['id']}").json() == meal


def test_log_meal_with_estimate_when_nothing_matches(alice):
    out = log(alice, "Plat du resto", f"{TODAY}T12:30", items=[{"food_query": "xyzzy", "grams": 300}],
              nutrients={"kcal": 800, "protein_g": 30})  # fmt: skip
    assert out["meal"]["nutrients"]["kcal"] == 800 and out["meal"]["items"] == []
    bare = log(alice, "Café", f"{TODAY}T09:00")
    assert bare["meal"]["nutrients"]["kcal"] is None and bare["meal"]["slot"] == "breakfast"


def test_at_is_in_the_users_time_zone(alice, bruno):
    # 13:00 UTC is 14:00 in Paris and 08:00 in New York.
    assert log(alice, "Sandwich", None)["meal"]["time"] == "14:00"
    ny = log(bruno, "Bagel", None)["meal"]
    assert ny["time"] == "08:00" and ny["slot"] == "breakfast"
    aware = log(alice, "Soupe", "2026-11-13T23:30:00+00:00")["meal"]
    assert (aware["date"], aware["time"], aware["slot"]) == ("2026-11-14", "00:30", "dinner")


def test_future_meals_are_refused(alice):
    assert alice.post("/v1/me/meals", json={"text": "Dîner", "at": f"{TODAY}T14:04"}).status_code == 201
    assert alice.post("/v1/me/meals", json={"text": "Dîner", "at": f"{TODAY}T20:00"}).status_code == 422
    assert alice.post("/v1/me/meals", json={"text": " "}).status_code == 422


def test_possible_duplicate_is_a_hint_not_a_refusal(alice):
    first = log(alice, "Curry de poulet", f"{TODAY}T12:00")["meal"]
    second = log(alice, "Curry de poulet + riz (1 boîte)", f"{TODAY}T12:40")
    assert second["created"] and second["possible_duplicate"]["id"] == first["id"]
    assert log(alice, "Curry de poulet", f"{TODAY}T13:00", repeat=True)["possible_duplicate"] is None
    assert log(alice, "Pâtes", f"{TODAY}T13:10")["possible_duplicate"] is None
    assert len(alice.get("/v1/me/meals").json()) == 4


def test_external_id_makes_logging_idempotent(alice):
    a = alice.post("/v1/me/meals", json={"text": "Riz", "at": f"{TODAY}T12:00", "external_id": "bob-1"})
    b = alice.post("/v1/me/meals", json={"text": "Riz", "at": f"{TODAY}T12:00", "external_id": "bob-1"})
    assert (a.status_code, b.status_code) == (201, 200)
    assert b.json()["created"] is False and b.json()["meal"]["id"] == a.json()["meal"]["id"]
    assert len(alice.get("/v1/me/meals").json()) == 1


def test_list_meals_by_range(alice):
    log(alice, "Hier", "2026-11-13T12:00")
    log(alice, "Midi", f"{TODAY}T12:00")
    log(alice, "Matin", f"{TODAY}T08:00")
    assert [m["text"] for m in alice.get("/v1/me/meals").json()] == ["Matin", "Midi"]
    both = alice.get("/v1/me/meals", params={"from": "2026-11-13", "to": TODAY}).json()
    assert [m["text"] for m in both] == ["Hier", "Matin", "Midi"]
    assert alice.get("/v1/me/meals", params={"from": TODAY, "to": "2026-11-13"}).status_code == 422


def test_patch_and_delete_meal(alice):
    meal = log(alice, "Pâtes", f"{TODAY}T12:30", items=[PASTA])["meal"]
    out = alice.patch(f"/v1/me/meals/{meal['id']}", json={"text": "Pâtes au thon", "items": [PASTA, TUNA]}).json()
    assert out["meal"]["text"] == "Pâtes au thon" and out["meal"]["nutrients"]["kcal"] == 426
    moved = alice.patch(f"/v1/me/meals/{meal['id']}", json={"at": f"{TODAY}T08:15"}).json()["meal"]
    assert moved["slot"] == "breakfast" and moved["nutrients"]["kcal"] == 426
    assert alice.patch(f"/v1/me/meals/{meal['id']}", json={"slot": "snack"}).json()["meal"]["slot"] == "snack"
    removed = alice.delete(f"/v1/me/meals/{meal['id']}")
    assert removed.status_code == 200 and removed.json()["text"] == "Pâtes au thon"
    assert alice.get(f"/v1/me/meals/{meal['id']}").status_code == 404
    assert alice.delete(f"/v1/me/meals/{meal['id']}").status_code == 404


def test_users_cannot_touch_each_others_meals(alice, bruno):
    meal = log(alice, "Pâtes", f"{TODAY}T12:30")["meal"]
    assert bruno.get(f"/v1/me/meals/{meal['id']}").status_code == 404
    assert bruno.patch(f"/v1/me/meals/{meal['id']}", json={"text": "x"}).status_code == 404
    assert bruno.delete(f"/v1/me/meals/{meal['id']}").status_code == 404
    assert bruno.get("/v1/me/meals", params={"from": "2026-11-01", "to": "2026-11-30"}).json() == []


# --- workouts -------------------------------------------------------------------------------------------------


def test_workouts(alice):
    run = alice.post("/v1/me/workouts", json={"date": TODAY, "km": 10, "kcal": 650, "external_id": "act-1"})
    assert run.status_code == 201 and run.json()["kcal_counted"] == 650
    again = alice.post("/v1/me/workouts", json={"date": TODAY, "km": 12, "external_id": "act-1"})
    assert again.status_code == 200 and again.json()["id"] == run.json()["id"]
    assert again.json()["kcal_counted"] == 840  # 12 km × 70 kg × 1 kcal
    gym = alice.post("/v1/me/workouts", json={"date": TODAY, "kind": "strength", "minutes": 45}).json()
    assert gym["kcal_counted"] == 0
    assert len(alice.get("/v1/me/workouts").json()) == 2
    assert alice.delete(f"/v1/me/workouts/{gym['id']}").status_code == 200
    assert alice.delete(f"/v1/me/workouts/{gym['id']}").status_code == 404
    assert alice.post("/v1/me/workouts", json={"date": TODAY, "km": -1}).status_code == 422


# --- days and weeks -------------------------------------------------------------------------------------------


def test_day_balance_with_and_without_workout(alice):
    log(alice, "Porridge", f"{TODAY}T08:00", items=[{"food_query": "flocons d'avoine", "grams": 60}])
    log(alice, "Pâtes au thon", f"{TODAY}T12:30", items=[PASTA, TUNA])
    day = alice.get("/v1/me/days/today").json()
    assert day["date"] == TODAY and day["meals"] == 2 and day["slots"] == ["breakfast", "lunch"]
    assert day["needs"]["total_kcal"] == 2334.5 and not day["training_day"] and day["carbs"] is None
    assert day["balance_kcal"] == round(day["totals"]["kcal"] - 2334.5, 1)
    assert [m["text"] for m in day["meals_logged"]] == ["Porridge", "Pâtes au thon"]
    assert day["log_issues"] == []  # 14:00: dinner is not over

    alice.post("/v1/me/workouts", json={"date": TODAY, "km": 10, "kcal": 650})
    day = alice.get(f"/v1/me/days/{TODAY}").json()
    assert day["needs"]["workouts_kcal"] == 650 and day["needs"]["total_kcal"] == 2984.5
    assert day["training_day"] and day["carbs"]["low"] == 5 and day["protein"]["status"] == "low"
    assert [w["kcal_counted"] for w in day["workouts"]] == [650]
    codes = [a["code"] for a in day["anomalies"]]
    # 60 g of oats is a light breakfast (< 250 kcal)
    assert codes == ["light_meal", "missing_meal", "low_intake", "low_protein", "low_carbs_workout_day"]
    assert day["anomalies"][1]["message"] == "aucune trace du dîner"
    en = alice.get("/v1/me/days/today", params={"lang": "en"}).json()
    assert en["anomalies"][1]["message"] == "no dinner logged"


def test_past_day_reports_missing_meals_and_duplicates(alice):
    a = log(alice, "Curry de poulet", "2026-11-13T12:00", nutrients={"kcal": 600})["meal"]
    b = log(alice, "Curry de poulet", "2026-11-13T12:30", nutrients={"kcal": 600})["meal"]
    day = alice.get("/v1/me/days/yesterday").json()
    assert day["date"] == "2026-11-13"
    issues = {i["code"]: i for i in day["log_issues"]}
    assert set(issues) == {"duplicate_meal", "no_trace"}
    assert issues["duplicate_meal"]["meal_ids"] == [a["id"], b["id"]]
    assert sorted(i["slot"] for i in day["log_issues"] if i["code"] == "no_trace") == ["breakfast", "dinner"]


def test_day_without_profile(bruno):
    day = bruno.get("/v1/me/days/today").json()
    assert day["needs"] is None and day["balance_kcal"] is None and day["timezone"] == "America/New_York"
    assert day["missing_profile"] == ["weight_kg", "height_cm", "birth_year", "sex"]
    assert day["log_issues"] == []  # 08:00 in New York: no slot is over yet


def test_day_rejects_bad_dates(alice):
    assert alice.get("/v1/me/days/someday").status_code == 422


def test_week(alice):
    for day, kcal in (("2026-11-12", 1000), ("2026-11-13", 1200)):
        log(alice, "Matin", f"{day}T08:00", nutrients={"kcal": kcal, "protein_g": 50})
        log(alice, "Soir", f"{day}T19:30", nutrients={"kcal": kcal, "protein_g": 50})
    log(alice, "Seul", "2026-11-10T12:00", nutrients={"kcal": 300})
    week = alice.get("/v1/me/weeks/yesterday").json()
    assert (week["start"], week["end"]) == ("2026-11-07", "2026-11-13") and len(week["days"]) == 7
    assert week["well_logged_days"] == 2 and week["average"]["kcal"] == 2200
    assert week["average_needs_kcal"] == 2334.5 and week["average_balance_kcal"] == -134.5
    assert week["protein_g_per_kg"] == round(100 / 70, 2)
    assert week["days"][-1]["meals_logged"][0]["text"] == "Matin"


# --- slot checks ----------------------------------------------------------------------------------------------


def test_slot_checks(alice, bruno):
    assert alice.get("/v1/me/slot-checks/today/lunch").json()["status"] is None
    put = alice.put("/v1/me/slot-checks/today/lunch", json={"status": "asked"}).json()
    assert (put["date"], put["slot"], put["status"]) == (TODAY, "lunch", "asked")
    alice.put(f"/v1/me/slot-checks/{TODAY}/lunch", json={"status": "answered"})
    assert alice.get("/v1/me/slot-checks/today/lunch").json()["status"] == "answered"
    assert alice.put("/v1/me/slot-checks/today/day", json={"status": "checked"}).status_code == 200
    assert alice.get("/v1/me/slot-checks/today/dinner").json()["status"] is None
    assert bruno.get(f"/v1/me/slot-checks/{TODAY}/lunch").json()["status"] is None
    assert alice.put("/v1/me/slot-checks/today/brunch", json={"status": "asked"}).status_code == 422
    assert alice.put("/v1/me/slot-checks/today/lunch", json={"status": "maybe"}).status_code == 422


# --- OpenAPI --------------------------------------------------------------------------------------------------


def test_openapi_lists_the_v1_routes(anon):
    paths = anon.get("/openapi.json").json()["paths"]
    for path in ("/v1/foods", "/v1/nutrients", "/v1/me/profile", "/v1/me/meals", "/v1/me/meals/{meal_id}",
                 "/v1/me/workouts", "/v1/me/days/{date}", "/v1/me/weeks/{date}",
                 "/v1/me/slot-checks/{date}/{slot}", "/v1/admin/users", "/health"):  # fmt: skip
        assert path in paths


def test_today_follows_the_clock(app, alice):
    app.state.clock = lambda: datetime.datetime(2026, 11, 14, 23, 30, tzinfo=datetime.UTC)  # 00:30 on the 15th in Paris
    assert alice.get("/v1/me/days/today").json()["date"] == "2026-11-15"


def test_make_user_helper_is_isolated(admin, app):
    assert make_user(admin, app, "eve").get("/v1/me/meals").json() == []
