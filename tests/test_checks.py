"""Log issues and anomalies: every rule at its threshold."""

import datetime

import pytest

from remy.checks import (
    DUPLICATE_HOURS,
    FULL_MEAL_KCAL,
    LIGHT_MAIN_MEAL_KCAL,
    Finding,
    Meal,
    anomalies,
    find_duplicate,
    log_issues,
    same_dish,
)
from remy.energy import Profile, Workout
from remy.foods import Nutrients
from remy.slots import Slot, slot_of

DAY = datetime.date(2026, 11, 14)
ATHLETE = Profile(weight_kg=70, height_cm=178, birth_year=1996, sex="male")  # needs 2334.5 kcal without workout
_ids = iter(range(1, 10_000))


def meal(time: str, text: str = "plat", kcal: float | None = 600, day: datetime.date = DAY, **kw) -> Meal:
    nutrients = kw.pop("nutrients", Nutrients(kcal=kcal, protein_g=kw.pop("protein", 40), carbs_g=kw.pop("carbs", 90)))
    return Meal(id=next(_ids), date=day, time=datetime.time.fromisoformat(time), text=text, nutrients=nutrients, **kw)


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


def full_day(**kw) -> list[Meal]:
    return [meal("08:00", "porridge", **kw), meal("12:30", "riz poulet", **kw), meal("19:30", "pâtes", **kw)]


# --- slots ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("time", "slot"),
    [
        ("03:59", Slot.DINNER),
        ("04:00", Slot.BREAKFAST),
        ("10:29", Slot.BREAKFAST),
        ("10:30", Slot.LUNCH),
        ("15:10", Slot.LUNCH),
        ("15:30", Slot.SNACK),
        ("17:29", Slot.SNACK),
        ("17:30", Slot.DINNER),
        ("23:59", Slot.DINNER),
    ],
)
def test_slot_of(time, slot):
    assert slot_of(datetime.time.fromisoformat(time)) == slot


def test_stored_slot_wins_over_time():
    assert meal("16:00", slot=Slot.LUNCH).meal_slot == Slot.LUNCH


# --- same dish ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Curry de poulet", "Curry de poulet + riz (1 boîte)", True),
        ("Curry de poulet", "curry POULET", True),
        ("Pâtes au thon", "Pâtes carbonara", False),
        ("Yaourt", "yaourt", True),
        ("Œufs brouillés", "œufs brouillés et pain", True),
        ("thé", "café", False),
        ("thé", "Thé", True),
    ],
)
def test_same_dish(a, b, same):
    assert same_dish(a, b) is same


# --- log issues -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("gap", "flagged"), [(DUPLICATE_HOURS * 60, True), (DUPLICATE_HOURS * 60 + 1, False)])
def test_duplicate_at_threshold(gap, flagged):
    first = datetime.datetime.combine(DAY, datetime.time(9, 0))
    second = first + datetime.timedelta(minutes=gap)
    meals = [meal("09:00", "Curry de poulet"), meal(f"{second:%H:%M}", "Curry de poulet + riz")]
    assert ("duplicate_meal" in codes(log_issues(meals, DAY))) is flagged


def test_duplicate_finding_details():
    a, b = meal("12:00", "Curry de poulet"), meal("12:40", "curry de poulet")
    (f,) = [f for f in log_issues([a, b], DAY) if f.code == "duplicate_meal"]
    assert f.meal_ids == [a.id, b.id] and f.values["first_time"] == "12:00"
    assert "noté deux fois" in f.message("fr") and "logged twice" in f.message("en")


def test_repeat_is_not_a_duplicate():
    meals = [meal("12:00", "Curry de poulet"), meal("12:40", "Curry de poulet", repeat=True)]
    assert "duplicate_meal" not in codes(log_issues(meals, DAY))


@pytest.mark.parametrize(("kcal", "flagged"), [(FULL_MEAL_KCAL, True), (FULL_MEAL_KCAL - 1, False)])
def test_two_full_meals_at_threshold(kcal, flagged):
    meals = [meal("12:00", "steak frites", kcal=kcal), meal("13:30", "lasagnes", kcal=kcal)]
    assert ("two_full_meals" in codes(log_issues(meals, DAY))) is flagged


def test_two_full_meals_not_repeated_when_already_a_duplicate():
    meals = [meal("12:00", "Curry de poulet"), meal("12:30", "Curry de poulet")]
    assert codes(log_issues(meals, DAY)).count("duplicate_meal") == 1
    assert "two_full_meals" not in codes(log_issues(meals, DAY))


@pytest.mark.parametrize(
    ("now", "missing"),
    [
        ("10:29", []),
        ("10:30", [Slot.BREAKFAST]),
        ("15:30", [Slot.BREAKFAST, Slot.LUNCH]),
        ("22:29", [Slot.BREAKFAST, Slot.LUNCH]),
        ("22:30", [Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER]),
    ],
)
def test_no_trace_once_the_slot_is_over(now, missing):
    at = datetime.datetime.combine(DAY, datetime.time.fromisoformat(now))
    found = [f.slot for f in log_issues([], DAY, at) if f.code == "no_trace"]
    assert found == missing


def test_no_trace_for_past_and_future_days():
    now = datetime.datetime.combine(DAY, datetime.time(9, 0))
    assert len(log_issues([], DAY - datetime.timedelta(days=1), now)) == 3
    assert log_issues([], DAY + datetime.timedelta(days=1), now) == []


def test_skipped_meal_is_a_trace():
    meals = [meal("08:00", "rien", kcal=0, skipped=True)]
    assert Slot.BREAKFAST not in [f.slot for f in log_issues(meals, DAY) if f.code == "no_trace"]


# --- possible duplicate when logging -------------------------------------------------------------------------


def test_find_duplicate_across_midnight():
    late = meal("23:00", "Curry de poulet", day=DAY - datetime.timedelta(days=1))
    at = datetime.datetime.combine(DAY, datetime.time(1, 30))
    assert find_duplicate([late], "curry de poulet", at) == late
    assert find_duplicate([late], "pâtes", at) is None
    assert find_duplicate([late], "curry de poulet", at + datetime.timedelta(hours=2)) is None


# --- anomalies ------------------------------------------------------------------------------------------------


def test_no_judgement_without_data():
    assert anomalies([], [Workout(date=DAY, kcal=650)], ATHLETE, DAY) == []


def test_bobs_evening_case():
    run = Workout(date=DAY, km=10, kcal=650)
    meals = [
        meal("08:00", "rien (petit-déjeuner sauté)", kcal=0, protein=0, carbs=0, skipped=True),
        meal("12:30", "Salade", kcal=180, protein=8, carbs=10),
        meal("20:00", "Pâtes", kcal=700, protein=25, carbs=100),
    ]
    found = anomalies(meals, [run], ATHLETE, DAY)
    assert codes(found) == ["skipped_meal", "light_meal", "low_intake", "low_protein", "low_carbs_workout_day"]
    assert [f.message("fr") for f in found[:2]] == ["petit-déjeuner sauté", "déjeuner très léger (~180 kcal)"]
    only_dinner = anomalies(meals[2:], [], ATHLETE, DAY)
    assert [f.message("fr") for f in only_dinner] == ["aucune trace du petit-déjeuner", "aucune trace du déjeuner"]
    assert [f.message("en") for f in only_dinner] == ["no breakfast logged", "no lunch logged"]


@pytest.mark.parametrize(("kcal", "flagged"), [(LIGHT_MAIN_MEAL_KCAL - 1, True), (LIGHT_MAIN_MEAL_KCAL, False)])
def test_light_meal_at_threshold(kcal, flagged):
    meals = [meal("08:00", kcal=kcal), meal("12:30"), meal("19:30")]
    assert ("light_meal" in codes(anomalies(meals, [], Profile(), DAY))) is flagged


def test_unknown_energy_is_not_a_light_meal():
    meals = [meal("08:00", kcal=None), meal("12:30"), meal("19:30")]
    assert "light_meal" not in codes(anomalies(meals, [], Profile(), DAY))


@pytest.mark.parametrize(
    ("ratio", "code"),
    [(0.74, "low_intake"), (0.75, None), (1.40, None), (1.41, "high_intake")],
)
def test_intake_thresholds(ratio, code):
    total = 2334.5 * ratio
    meals = [meal("08:00", kcal=total / 2, protein=100), meal("12:30", kcal=total / 2, protein=100)]
    found = [f.code for f in anomalies(meals, [], ATHLETE, DAY) if f.code in ("low_intake", "high_intake")]
    assert found == ([code] if code else [])


def test_intake_needs_two_meals():
    assert "low_intake" not in codes(anomalies([meal("12:30", kcal=300)], [], ATHLETE, DAY))


def test_intake_counts_workouts():
    meals = [meal("08:00", kcal=1000), meal("12:30", kcal=1000)]  # 2000 / 2334.5 = 0.86 without the run
    assert "low_intake" not in codes(anomalies(meals, [], ATHLETE, DAY))
    assert "low_intake" in codes(anomalies(meals, [Workout(date=DAY, kcal=700)], ATHLETE, DAY))  # 2000 / 3034.5


@pytest.mark.parametrize(("protein", "flagged"), [(83.9, True), (84, False)])  # 1.2 g/kg × 70 kg = 84 g
def test_low_protein_at_threshold(protein, flagged):
    meals = [meal("08:00", kcal=1200, protein=protein / 2), meal("12:30", kcal=1200, protein=protein / 2)]
    assert ("low_protein" in codes(anomalies(meals, [], ATHLETE, DAY))) is flagged


@pytest.mark.parametrize(("carbs", "workout", "flagged"), [(279, True, True), (280, True, False), (100, False, False)])
def test_low_carbs_only_on_workout_days(carbs, workout, flagged):  # 4 g/kg × 70 kg = 280 g
    meals = [meal("08:00", kcal=1500, carbs=carbs / 2), meal("12:30", kcal=1500, carbs=carbs / 2)]
    workouts = [Workout(date=DAY, km=8)] if workout else []
    assert ("low_carbs_workout_day" in codes(anomalies(meals, workouts, ATHLETE, DAY))) is flagged


def test_lunch_at_1510_and_snack_do_not_hide_main_meals():
    meals = [meal("08:00"), meal("15:10"), meal("19:30"), meal("16:00", slot=Slot.SNACK)]
    assert anomalies(meals, [], Profile(), DAY) == []


def test_messages_format_numbers_per_language():
    f = Finding(code="low_protein", date=DAY, values={"grams": 1200, "g_per_kg": 1.1})
    assert f.message("fr") == "protéines basses : 1 200 g (1,1 g/kg)"
    assert f.message("en") == "low protein: 1,200 g (1.1 g/kg)"
