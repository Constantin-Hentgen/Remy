"""Conversions between database rows, library models and API models."""

import datetime

from remy import energy
from remy.checks import Finding, Meal
from remy.energy import Profile, Workout
from remy.foods import NUTRIENTS, Food, Lang, Nutrients
from remy.nutrients import MealItem
from remy.schemas import FindingOut, FoodOut, Goals, MealOut, ProfileOut, WorkoutOut
from remy.service.db import MealRow, User, WorkoutRow
from remy.slots import Slot


def food_out(food: Food, lang: Lang) -> FoodOut:
    return FoodOut(**food.model_dump(), name=food.name(lang))


def profile_of(user: User) -> Profile:
    return Profile(
        weight_kg=user.weight_kg,
        height_cm=user.height_cm,
        birth_year=user.birth_year,
        sex=user.sex,
        activity_factor=user.activity_factor,
    )


def profile_out(user: User, today: datetime.date) -> ProfileOut:
    profile = profile_of(user)
    base = energy.bmr(profile, today)
    factor = profile.activity_factor or energy.ACTIVITY_FACTOR
    return ProfileOut(
        **profile.model_dump(),
        timezone=user.timezone,
        lang=user.lang,
        goals=Goals(**(user.goals or {})),
        missing=profile.missing(),
        bmr_kcal=round(base, 1) if base is not None else None,
        rest_day_needs_kcal=round(base * factor, 1) if base is not None else None,
    )


def nutrients_of(row: MealRow) -> Nutrients:
    return Nutrients(**{k: getattr(row, k) for k in NUTRIENTS})


def meal_out(row: MealRow) -> MealOut:
    return MealOut(
        id=row.id,
        date=row.date,
        time=f"{row.time:%H:%M}",
        slot=Slot(row.slot),
        text=row.text,
        nutrients=nutrients_of(row),
        items=[MealItem(**i) for i in row.items or []],
        source=row.source,
        repeat=row.repeat,
        skipped=row.skipped,
        external_id=row.external_id,
        created_at=row.created_at,
    )


def meal_core(row: MealRow) -> Meal:
    return Meal(
        id=row.id,
        date=row.date,
        time=row.time,
        slot=Slot(row.slot),
        text=row.text,
        nutrients=nutrients_of(row),
        repeat=row.repeat,
        skipped=row.skipped,
    )


def workout_core(row: WorkoutRow) -> Workout:
    return Workout(date=row.date, kind=row.kind, kcal=row.kcal, km=row.km, minutes=row.minutes)


def workout_out(row: WorkoutRow, weight_kg: float | None) -> WorkoutOut:
    return WorkoutOut(
        id=row.id,
        date=row.date,
        kind=row.kind,
        kcal=row.kcal,
        km=row.km,
        minutes=row.minutes,
        external_id=row.external_id,
        kcal_counted=round(energy.workout_kcal(workout_core(row), weight_kg), 1),
    )


def finding_out(finding: Finding, lang: Lang) -> FindingOut:
    return FindingOut(**finding.model_dump(), message=finding.message(lang))
