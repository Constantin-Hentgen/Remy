"""Energy needs: Mifflin–St Jeor, activity factor, workout calories."""

import datetime

import pytest
from pydantic import ValidationError

from remy.energy import ACTIVITY_FACTOR, Profile, Sex, Workout, bmr, needs, workout_kcal

DAY = datetime.date(2026, 11, 14)
ATHLETE = Profile(weight_kg=70, height_cm=178, birth_year=1996, sex="homme")


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (ATHLETE, 1667.5),  # 700 + 1112.5 - 150 + 5 (Bob's reference case)
        (Profile(weight_kg=60, height_cm=165, birth_year=1986, sex="female"), 1270.25),  # 600 + 1031.25 - 200 - 161
        (Profile(weight_kg=70, height_cm=178, birth_year=1996), None),
        (Profile(), None),
    ],
)
def test_bmr(profile, expected):
    assert bmr(profile, DAY) == expected


@pytest.mark.parametrize(
    ("alias", "sex"),
    [
        ("homme", Sex.MALE),
        ("H", Sex.MALE),
        ("m", Sex.MALE),
        ("femme", Sex.FEMALE),
        ("F", Sex.FEMALE),
        ("female", Sex.FEMALE),
    ],
)
def test_sex_aliases(alias, sex):
    assert Profile(sex=alias).sex == sex


@pytest.mark.parametrize(
    "bad",
    [
        {"weight_kg": 5},
        {"weight_kg": 400},
        {"height_cm": 50},
        {"birth_year": 1800},
        {"birth_year": datetime.date.today().year},
        {"sex": "other"},
        {"activity_factor": 0.5},
    ],
)
def test_profile_validation(bad):
    with pytest.raises(ValidationError):
        Profile(**bad)


def test_missing_fields():
    assert Profile(weight_kg=70).missing() == ["height_cm", "birth_year", "sex"]
    assert ATHLETE.missing() == []


@pytest.mark.parametrize(
    ("workout", "weight", "expected"),
    [
        (Workout(date=DAY, kcal=650, km=10), 70, 650),  # device calories win
        (Workout(date=DAY, km=10), 70, 700),  # 1 kcal/kg/km
        (Workout(date=DAY, km=10), None, 700),  # default 70 kg
        (Workout(date=DAY, km=10, kcal=0), 60, 600),
        (Workout(date=DAY, minutes=60), 70, 0),  # duration alone: no guess
    ],
)
def test_workout_kcal(workout, weight, expected):
    assert workout_kcal(workout, weight) == expected


def test_needs_without_workout():
    n = needs(ATHLETE, [], DAY)
    assert n.bmr == 1667.5 and n.activity_factor == ACTIVITY_FACTOR
    assert n.daily_life_kcal == 2334.5 and n.workouts_kcal == 0 and n.total_kcal == 2334.5


def test_needs_with_device_calories():
    n = needs(ATHLETE, [Workout(date=DAY, kcal=650, km=10)], DAY)
    assert n.total_kcal == round(1667.5 * 1.4 + 650, 1)


def test_needs_with_distance_only_and_other_days_ignored():
    workouts = [Workout(date=DAY, km=12), Workout(date=DAY - datetime.timedelta(days=1), kcal=900)]
    assert needs(ATHLETE, workouts, DAY).workouts_kcal == 840


def test_activity_factor_override():
    p = ATHLETE.model_copy(update={"activity_factor": 1.2})
    assert needs(p, [], DAY).daily_life_kcal == 2001.0


def test_no_needs_for_incomplete_profile():
    assert needs(Profile(weight_kg=70), [Workout(date=DAY, kcal=500)], DAY) is None
