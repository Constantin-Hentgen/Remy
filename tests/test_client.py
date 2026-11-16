"""The typed client, run against the app in-process (the TestClient is an httpx.Client)."""

import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from remy.client import RemyClient, RemyError
from remy.schemas import DayOut, MealLogged, ProfileIn
from tests.conftest import TODAY

TODAY_DATE = datetime.date.fromisoformat(TODAY)


@pytest.fixture
def remy(app, admin):
    key = admin.post("/v1/admin/users", json={"name": "client-user"}).json()["api_key"]["key"]
    http = TestClient(app)
    with RemyClient(api_key=key, http=http) as client:
        yield client


def test_foods_and_nutrients(remy):
    found = remy.foods("riz blanc cuit", limit=2)
    assert found.foods[0].code == "9104" and found.lang == "fr" and len(found.foods) == 2
    assert remy.foods("riz", lang="en").lang == "en"
    out = remy.nutrients([{"food_query": "pâtes cuites", "grams": 250}, {"food_code": "26039", "grams": 100}])
    assert out.totals.kcal == 426 and out.warnings == []


def test_profile(remy):
    assert remy.profile().missing == ["weight_kg", "height_cm", "birth_year", "sex"]
    remy.put_profile(ProfileIn(weight_kg=70, height_cm=178, birth_year=1996, sex="male"))
    p = remy.patch_profile(weight_kg=72, goals={"target_weight_kg": 68})
    assert p.weight_kg == 72 and p.height_cm == 178 and p.goals.target_weight_kg == 68 and p.bmr_kcal
    assert remy.patch_profile(activity_factor=None).activity_factor is None


def test_meal_lifecycle(remy):
    logged = remy.log_meal(
        "Curry de poulet", at=f"{TODAY}T12:00", items=[{"food_query": "riz blanc cuit", "grams": 200}]
    )
    assert isinstance(logged, MealLogged) and logged.created and logged.meal.slot == "lunch"
    assert logged.meal.nutrients.kcal and logged.meal.items[0].food_code == "9104"
    again = remy.log_meal("curry de poulet", at=f"{TODAY}T12:30")
    assert again.possible_duplicate and again.possible_duplicate.id == logged.meal.id
    assert [m.text for m in remy.meals(TODAY_DATE)] == ["Curry de poulet", "curry de poulet"]
    assert remy.meal(logged.meal.id).text == "Curry de poulet"
    assert remy.patch_meal(logged.meal.id, skipped=True).meal.skipped
    assert remy.delete_meal(again.meal.id).id == again.meal.id
    assert len(remy.meals("today", "today")) == 1


def test_idempotent_logging(remy):
    first = remy.log_meal("Riz", at=f"{TODAY}T12:00", external_id="bob-1")
    second = remy.log_meal("Riz", at=f"{TODAY}T12:00", external_id="bob-1")
    assert first.created and not second.created and first.meal.id == second.meal.id


def test_workouts_days_weeks_and_slot_checks(remy):
    remy.put_profile(ProfileIn(weight_kg=70, height_cm=178, birth_year=1996, sex="male"))
    run = remy.add_workout(date=TODAY_DATE, km=10, kcal=650, external_id="a1")
    assert run.kcal_counted == 650 and [w.id for w in remy.workouts("today")] == [run.id]
    day = remy.day()
    assert isinstance(day, DayOut) and day.date == TODAY_DATE and day.needs.workouts_kcal == 650
    assert remy.day("today", lang="en").anomalies == []  # nothing logged: no judgement
    week = remy.week("today")
    assert week.end == TODAY_DATE and len(week.days) == 7
    assert remy.slot_check("today", "lunch").status is None
    assert remy.set_slot_check("today", "lunch", "asked").status == "asked"
    assert remy.slot_check(TODAY_DATE, "lunch").status == "asked"
    assert remy.delete_workout(run.id).id == run.id


def test_errors_carry_status_and_detail(remy, app):
    with pytest.raises(RemyError) as e:
        remy.meal(999)
    assert e.value.status_code == 404 and "no meal 999" in str(e.value)
    with pytest.raises(RemyError) as e:
        remy.log_meal("Dîner", at=f"{TODAY}T23:00")
    assert e.value.status_code == 422 and "future" in str(e.value.detail)
    with RemyClient(api_key="remy_wrong", http=TestClient(app)) as anonymous, pytest.raises(RemyError) as e:
        anonymous.profile()
    assert e.value.status_code == 401


def test_owns_its_http_client_only_when_it_built_it():
    own = RemyClient("http://remy:8000/", api_key="k")
    assert isinstance(own._http, httpx.Client) and str(own._http.base_url) == "http://remy:8000"
    assert own._http.headers["Authorization"] == "Bearer k"
    own.close()
    assert own._http.is_closed
    shared = httpx.Client(base_url="http://x")
    RemyClient(http=shared).close()
    assert not shared.is_closed
    shared.close()
