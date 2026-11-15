"""Day and week summaries (Bob's /nutrition and evening recap, as data)."""

import datetime

from remy import summary
from remy.checks import Meal
from remy.energy import Profile, Workout
from remy.foods import Nutrients
from remy.nutrients import compute
from remy.slots import Slot

DAY = datetime.date(2026, 11, 14)
ATHLETE = Profile(weight_kg=70, height_cm=178, birth_year=1996, sex="male")
RUN = Workout(date=DAY, km=10, kcal=650)


def logged(day: datetime.date, time: str, text: str, items: list[dict], meal_id: int) -> Meal:
    return Meal(id=meal_id, date=day, time=datetime.time.fromisoformat(time), text=text,
                nutrients=compute(items).totals)  # fmt: skip


def test_bobs_energy_balance_case():
    meals = [
        logged(DAY, "08:00", "porridge", [{"food_query": "flocons d'avoine", "grams": 60}], 1),
        logged(DAY, "12:30", "pâtes", [{"food_query": "pâtes cuites", "grams": 250}], 2),
    ]
    now = datetime.datetime.combine(DAY, datetime.time(14, 0))
    s = summary.day(meals, [RUN], ATHLETE, DAY, now)
    assert s.meals == 2 and s.slots == [Slot.BREAKFAST, Slot.LUNCH] and s.training_day
    assert s.needs.total_kcal == round(1667.5 * 1.4 + 650, 1) and s.workouts_kcal == 650
    assert s.balance_kcal == round(s.totals.kcal - s.needs.total_kcal, 1) and s.balance_kcal < 0
    assert s.protein.low == 1.4 and s.protein.high == 1.8 and s.protein.status == "low"
    assert s.carbs is not None and (s.carbs.low, s.carbs.high) == (5.0, 7.0)
    assert s.log_issues == []  # dinner is not over at 14:00


def test_day_without_profile_or_workout():
    s = summary.day([], [], Profile(), DAY)
    assert s.needs is None and s.balance_kcal is None and s.protein is None and s.carbs is None
    assert s.missing_profile == ["weight_kg", "height_cm", "birth_year", "sex"]
    assert [f.code for f in s.log_issues] == ["no_trace"] * 3 and s.anomalies == []


def test_rest_day_has_no_carbs_target():
    s = summary.day([], [], ATHLETE, DAY)
    assert not s.training_day and s.carbs is None and s.protein.status == "low" and s.balance_kcal == -2334.5


def test_skipped_entries_are_not_meals():
    meals = [Meal(id=1, date=DAY, time=datetime.time(8), text="rien", skipped=True,
                  nutrients=Nutrients(kcal=0))]  # fmt: skip
    s = summary.day(meals, [], ATHLETE, DAY)
    assert s.meals == 0 and s.slots == []


def _meal(day: datetime.date, time: str, kcal: float, meal_id: int) -> Meal:
    return Meal(id=meal_id, date=day, time=datetime.time.fromisoformat(time), text=f"plat {meal_id}",
                nutrients=Nutrients(kcal=kcal, protein_g=kcal / 20, carbs_g=kcal / 8))  # fmt: skip


def test_week_averages_well_logged_days_only():
    d = [DAY - datetime.timedelta(days=i) for i in range(7)]
    meals = [
        _meal(d[0], "08:00", 1000, 1), _meal(d[0], "12:30", 1400, 2),  # 2400
        _meal(d[1], "08:00", 800, 3), _meal(d[1], "19:30", 1200, 4),  # 2000
        _meal(d[2], "12:30", 300, 5),  # one meal: not counted
    ]  # fmt: skip
    w = summary.week(meals, [RUN], ATHLETE, DAY)
    assert w.start == DAY - datetime.timedelta(days=6) and w.end == DAY and len(w.days) == 7
    assert [x.date for x in w.days] == sorted(d)
    assert w.well_logged_days == 2 and w.average.kcal == 2200
    assert w.average_needs_kcal == round((1667.5 * 1.4 + 650 + 1667.5 * 1.4) / 2, 1)
    assert w.average_balance_kcal == round(2200 - w.average_needs_kcal, 1)
    assert w.protein_g_per_kg == round(110 / 70, 2)


def test_week_without_data():
    w = summary.week([], [], Profile(), DAY)
    assert w.well_logged_days == 0 and w.average is None and w.average_needs_kcal is None
    assert w.protein_g_per_kg is None
