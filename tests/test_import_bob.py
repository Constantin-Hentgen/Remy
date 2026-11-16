"""Import of Bob's state file. The state below is synthetic: invented meals, in the format of ``bob/memory.py``."""

import json

import pytest
from fastapi.testclient import TestClient

from remy import cli
from remy.client import RemyClient
from remy.importers import bob
from remy.service.settings import get_settings
from tests.conftest import make_user


def synthetic_state() -> dict:
    return {
        "memories": [{"id": 1, "category": "autre", "text": "ignored"}],
        "history": {"1": [{"role": "user", "content": "ignored"}]},
        "next_meal_id": 9,
        "meals": [
            {
                "id": 1,
                "date": "2026-11-12",
                "time": "08:10",
                "slot": "petit-déjeuner",
                "text": "flocons d'avoine, banane",
                "kcal": 306,
                "protein_g": 9,
                "carbs_g": 52,
                "fat_g": 5,
                "fiber_g": 8,
                "sugars_g": 14,
                "salt_g": 0.0,
                "items": [
                    {
                        "food": "flocons d'avoine",
                        "code": "9410",
                        "ciqual": "Flocons d'avoine",
                        "grams": 60,
                        "kcal": 222.0,
                        "protein_g": 8.0,
                        "carbs_g": 36.0,
                        "fat_g": 4.0,
                        "fiber_g": 6.0,
                        "sugars_g": 0.7,
                        "salt_g": 0.0,
                    },
                    {
                        "food": "banane",
                        "code": "13005",
                        "ciqual": "Banane, pulpe, crue",
                        "grams": 100,
                        "kcal": 90.5,
                        "protein_g": 1.1,
                        "carbs_g": 19.7,
                        "fat_g": 0.3,
                        "fiber_g": 2.7,
                        "sugars_g": 15.6,
                        "salt_g": 0.0,
                    },
                ],
                "source": "conversation",
            },
            {
                "id": 2,
                "date": "2026-11-12",
                "time": "12:30",
                "slot": "déjeuner",
                "text": "pâtes au thon",
                "kcal": 650,
                "protein_g": 32,
                "carbs_g": 88,
                "fat_g": 18,
                "items": [],
                "source": "bouton",
                "repeat": True,
            },
            {
                "id": 3,
                "date": "2026-11-12",
                "time": "15:30",
                "slot": "collation",
                "text": "rien (collation sauté)",
                "kcal": 0,
                "protein_g": 0,
                "carbs_g": 0,
                "items": [],
                "source": "bouton",
            },
            {
                "id": 4,
                "date": "2026-11-13",
                "time": "19:45",
                "slot": "dîner",
                "text": "  soupe   de légumes  ",
                "kcal": 120,
                "items": [{"food": "soupe", "code": "", "grams": 300}, "garbage"],
                "source": "conversation",
            },
            {"id": 5, "date": "not a date", "time": "12:00", "text": "broken date"},
            {"id": 6, "date": "2026-11-13", "time": "12:00", "text": ""},
            {"date": "2026-11-13", "time": "12:00", "text": "no id"},
            "not an object",
            {"id": 1, "date": "2026-11-13", "time": "09:00", "text": "same id again"},
        ],
        "profile": {"weight_kg": 70.5, "height_cm": 178, "birth_year": 1990, "sex": "homme"},
        "meal_checks": {
            "2026-11-12 petit-déjeuner": "answered",
            "2026-11-12 déjeuner": "asked",
            "2026-11-12 nutrition": "checked",
            "2026-11-13 dîner": "skipped",
            "2026-11-13 brunch": "asked",
            "2026-11-13 déjeuner": "maybe",
            "garbage": "asked",
        },
    }


# --- parsing ------------------------------------------------------------------------------------------------------


def test_parse_reads_meals_profile_and_checks():
    state = bob.parse(synthetic_state())
    by_id = {m.external_id: m for m in state.meals}
    assert sorted(by_id) == ["bob:meal:1", "bob:meal:2", "bob:meal:3", "bob:meal:4"]

    oats = by_id["bob:meal:1"]
    assert (oats.date.isoformat(), f"{oats.time:%H:%M}", oats.slot.value) == ("2026-11-12", "08:10", "breakfast")
    assert oats.nutrients.kcal == 306 and oats.nutrients.protein_g == 9 and oats.source == "conversation"
    assert [(i.food_code, i.label, i.food_name, i.grams) for i in oats.items] == [
        ("9410", "flocons d'avoine", "Flocons d'avoine", 60),
        ("13005", "banane", "Banane, pulpe, crue", 100),
    ]
    assert oats.items[1].nutrients.kcal == 90.5 and not oats.skipped and not oats.repeat

    lunch = by_id["bob:meal:2"]
    assert lunch.slot.value == "lunch" and lunch.repeat and lunch.items == [] and lunch.source == "bouton"
    assert by_id["bob:meal:3"].skipped and by_id["bob:meal:3"].slot.value == "snack"
    soup = by_id["bob:meal:4"]
    assert soup.text == "soupe de légumes" and soup.items == [] and soup.nutrients.protein_g is None

    assert state.profile == {"weight_kg": 70.5, "height_cm": 178, "birth_year": 1990, "sex": "male"}
    assert {(c.date.isoformat(), c.slot, c.status) for c in state.checks} == {
        ("2026-11-12", "breakfast", "answered"),
        ("2026-11-12", "lunch", "asked"),
        ("2026-11-12", "day", "checked"),
        ("2026-11-13", "dinner", "skipped"),
    }


def test_parse_reports_what_it_cannot_read():
    problems = [(p.section, p.ref, p.detail) for p in bob.parse(synthetic_state()).problems]
    meals = [(ref, detail) for section, ref, detail in problems if section == "meals"]
    assert [ref for ref, _ in meals] == ["5", "6", "6", "7", "1"]  # no id: reported by position
    assert "Invalid isoformat" in meals[0][1] and meals[1][1] == "empty text" and meals[2][1] == "no id"
    assert meals[3][1] == "not an object" and meals[4][1] == "duplicate id in the file"
    checks = {ref: detail for section, ref, detail in problems if section == "meal_checks"}
    assert set(checks) == {"2026-11-13 brunch", "2026-11-13 déjeuner", "garbage"}
    assert "unknown slot" in checks["2026-11-13 brunch"] and "unknown status" in checks["2026-11-13 déjeuner"]


def test_parse_profile_keeps_valid_fields_only():
    state = bob.parse({"profile": {"weight_kg": 7, "height_cm": 180, "birth_year": 1990, "sex": "x", "bike": 1}})
    assert state.profile == {"height_cm": 180, "birth_year": 1990}
    assert {p.ref for p in state.problems} == {"weight_kg", "sex"}


def test_parse_tolerates_garbage():
    for state in (
        {},
        {"meals": None, "profile": None, "meal_checks": None},
        {"meals": "x", "profile": [], "meal_checks": []},
    ):
        parsed = bob.parse(state)
        assert parsed.meals == [] and parsed.profile == {} and parsed.checks == [] and parsed.problems == []


# --- endpoint -----------------------------------------------------------------------------------------------------


@pytest.fixture
def alice(app, admin):
    return make_user(admin, app, "alice")  # Europe/Paris, today is 2026-11-14


def test_import_then_import_again(alice):
    first = alice.post("/v1/me/import/bob", json=synthetic_state())
    assert first.status_code == 200, first.text
    report = first.json()
    assert report["dry_run"] is False
    assert report["meals"] == {"imported": 4, "already_present": 0, "invalid": 5}
    assert report["meal_checks"] == {"imported": 4, "already_present": 0, "invalid": 3}
    assert report["profile_set"] == ["weight_kg", "height_cm", "birth_year", "sex"] and report["profile_kept"] == []

    meals = alice.get("/v1/me/meals", params={"from": "2026-11-12", "to": "2026-11-13"}).json()
    assert [(m["date"], m["time"], m["slot"], m["text"]) for m in meals] == [
        ("2026-11-12", "08:10", "breakfast", "flocons d'avoine, banane"),
        ("2026-11-12", "12:30", "lunch", "pâtes au thon"),
        ("2026-11-12", "15:30", "snack", "rien (collation sauté)"),
        ("2026-11-13", "19:45", "dinner", "soupe de légumes"),
    ]
    assert meals[0]["nutrients"]["kcal"] == 306 and meals[0]["items"][1]["food_name"] == "Banane, pulpe, crue"
    assert meals[1]["repeat"] and meals[2]["skipped"] and meals[0]["external_id"] == "bob:meal:1"

    profile = alice.get("/v1/me/profile").json()
    assert profile["weight_kg"] == 70.5 and profile["sex"] == "male" and profile["missing"] == []
    assert alice.get("/v1/me/slot-checks/2026-11-12/day").json()["status"] == "checked"
    assert alice.get("/v1/me/slot-checks/2026-11-12/lunch").json()["status"] == "asked"

    again = alice.post("/v1/me/import/bob", json=synthetic_state()).json()
    assert again["meals"] == {"imported": 0, "already_present": 4, "invalid": 5}
    assert again["meal_checks"]["imported"] == 0 and again["meal_checks"]["already_present"] == 4
    assert again["profile_set"] == [] and sorted(again["profile_kept"]) == [
        "birth_year",
        "height_cm",
        "sex",
        "weight_kg",
    ]
    assert len(alice.get("/v1/me/meals", params={"from": "2026-11-01", "to": "2026-11-14"}).json()) == 4


def test_dry_run_writes_nothing(alice):
    report = alice.post("/v1/me/import/bob", params={"dry_run": "true"}, json=synthetic_state()).json()
    assert report["dry_run"] is True and report["meals"]["imported"] == 4 and report["profile_set"]
    assert alice.get("/v1/me/meals", params={"from": "2026-11-01", "to": "2026-11-14"}).json() == []
    assert alice.get("/v1/me/profile").json()["weight_kg"] is None
    assert alice.get("/v1/me/slot-checks/2026-11-12/day").json()["status"] is None


def test_existing_remy_data_is_never_overwritten(alice):
    alice.put("/v1/me/profile", json={"weight_kg": 65})
    alice.put("/v1/me/slot-checks/2026-11-12/lunch", json={"status": "answered"})
    report = alice.post("/v1/me/import/bob", json=synthetic_state()).json()
    assert report["profile_kept"] == ["weight_kg"] and "weight_kg" not in report["profile_set"]
    assert alice.get("/v1/me/profile").json()["weight_kg"] == 65
    assert alice.get("/v1/me/slot-checks/2026-11-12/lunch").json()["status"] == "answered"


def test_imported_history_feeds_the_day_view(alice):
    alice.post("/v1/me/import/bob", json=synthetic_state())
    day = alice.get("/v1/me/days/2026-11-12").json()
    assert day["meals"] == 2 and day["totals"]["kcal"] == 956 and day["needs"]["bmr"]
    assert [m["skipped"] for m in day["meals_logged"]] == [False, False, True]
    assert alice.post("/v1/me/import/bob", json={}).json()["meals"]["imported"] == 0


def test_imports_are_per_user_and_private(app, admin, alice):
    other = make_user(admin, app, "other")
    alice.post("/v1/me/import/bob", json=synthetic_state())
    assert other.post("/v1/me/import/bob", json=synthetic_state()).json()["meals"]["imported"] == 4
    assert len(other.get("/v1/me/meals", params={"from": "2026-11-12", "to": "2026-11-13"}).json()) == 4
    assert TestClient(app).post("/v1/me/import/bob", json={}).status_code == 401


def test_client_method(app, admin):
    key = admin.post("/v1/admin/users", json={"name": "carol"}).json()["api_key"]["key"]
    with RemyClient(api_key=key, http=TestClient(app)) as remy:
        assert remy.import_bob(synthetic_state(), dry_run=True).meals.imported == 4
        assert remy.import_bob(synthetic_state()).meals.imported == 4
        assert remy.import_bob(synthetic_state()).meals.already_present == 4


# --- command line -------------------------------------------------------------------------------------------------


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'remy.db'}")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_cli_import(database, capsys):
    state_file = database / "coach_state.json"
    state_file.write_text(json.dumps(synthetic_state()), encoding="utf-8")
    assert cli.main(["user", "create", "alice"]) == 0
    capsys.readouterr()

    assert cli.main(["import", "bob", str(state_file), "--user", "alice", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run, nothing written: meals: 4 imported" in out and "meals 5: invalid date" not in out

    assert cli.main(["import", "bob", str(state_file), "--user", "alice"]) == 0
    assert "meals: 4 imported, 0 already there, 5 unreadable" in capsys.readouterr().out
    assert cli.main(["import", "bob", str(state_file), "--user", "alice"]) == 0
    out = capsys.readouterr().out
    assert "meals: 0 imported, 4 already there" in out and "kept weight_kg" in out


def test_cli_import_errors(database, capsys):
    assert cli.main(["user", "create", "alice"]) == 0
    capsys.readouterr()
    assert cli.main(["import", "bob", str(database / "missing.json"), "--user", "alice"]) == 1
    broken = database / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert cli.main(["import", "bob", str(broken), "--user", "alice"]) == 1
    listing = database / "list.json"
    listing.write_text("[]", encoding="utf-8")
    assert cli.main(["import", "bob", str(listing), "--user", "alice"]) == 1
    assert cli.main(["import", "bob", str(listing), "--user", "nobody"]) == 1
    err = capsys.readouterr().err
    assert "cannot read" in err and "not a Bob state file" in err and "no user 'nobody'" in err
