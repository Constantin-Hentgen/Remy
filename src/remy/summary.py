"""Day and week summaries: what was eaten against what the day cost.

This is what Bob's ``/nutrition`` command and evening recap show, as data: totals, needs (BMR, daily activity,
workouts), the balance, protein and carbs in g/kg against the endurance ranges, and the findings of
:mod:`remy.checks`.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, Field

from remy.checks import MIN_MEALS_TO_JUDGE_INTAKE, Finding, Meal, anomalies, eaten, log_issues, totals
from remy.energy import (
    CARBS_G_PER_KG_TRAINING,
    PROTEIN_G_PER_KG,
    Needs,
    Profile,
    Workout,
    day_workouts,
    needs,
    workouts_kcal,
)
from remy.foods import NUTRIENTS, Nutrients
from remy.slots import Slot

WEEK_DAYS = 7


class MacroCheck(BaseModel):
    """A macronutrient against its reference range, in g per kg of body weight."""

    grams: float
    g_per_kg: float
    low: float
    high: float
    status: Literal["low", "ok", "high"]


def _macro(grams: float, weight_kg: float, low: float, high: float) -> MacroCheck:
    per_kg = round(grams / weight_kg, 2)
    status: Literal["low", "ok", "high"] = "low" if per_kg < low else "high" if per_kg > high else "ok"
    return MacroCheck(grams=round(grams, 1), g_per_kg=per_kg, low=low, high=high, status=status)


class DaySummary(BaseModel):
    date: datetime.date
    totals: Nutrients = Field(description="What was eaten (skipped entries excluded).")
    meals: int = Field(description="Number of meals eaten.")
    slots: list[Slot] = Field(description="Slots with at least one meal eaten.")
    training_day: bool
    workouts_kcal: float
    needs: Needs | None = Field(description="None while the profile is incomplete (see missing_profile).")
    missing_profile: list[str]
    balance_kcal: float | None = Field(description="Intake minus needs: negative is a deficit.")
    protein: MacroCheck | None = Field(description="Against 1.4–1.8 g/kg; None without a weight.")
    carbs: MacroCheck | None = Field(description="Against 5–7 g/kg, on training days only.")
    log_issues: list[Finding]
    anomalies: list[Finding]


def day(
    meals: list[Meal],
    workouts: list[Workout],
    profile: Profile,
    date: datetime.date,
    now: datetime.datetime | None = None,
) -> DaySummary:
    """Summary of ``date``. ``now`` is the user's local time; ``None`` means the day is over."""
    of_day = [m for m in meals if m.date == date]
    done = eaten(of_day)
    t = totals(of_day)
    need = needs(profile, workouts, date)
    training = bool(day_workouts(workouts, date))
    w = profile.weight_kg
    return DaySummary(
        date=date,
        totals=t,
        meals=len(done),
        slots=sorted({m.meal_slot for m in done}, key=list(Slot).index),
        training_day=training,
        workouts_kcal=workouts_kcal(profile, workouts, date),
        needs=need,
        missing_profile=profile.missing(),
        balance_kcal=round((t.kcal or 0) - need.total_kcal, 1) if need else None,
        protein=_macro(t.protein_g or 0, w, *PROTEIN_G_PER_KG) if w else None,
        carbs=_macro(t.carbs_g or 0, w, *CARBS_G_PER_KG_TRAINING) if w and training else None,
        log_issues=log_issues(meals, date, now),
        anomalies=anomalies(meals, workouts, profile, date),
    )


class WeekSummary(BaseModel):
    start: datetime.date
    end: datetime.date
    days: list[DaySummary]
    well_logged_days: int = Field(description=f"Days with at least {MIN_MEALS_TO_JUDGE_INTAKE} meals logged.")
    average: Nutrients | None = Field(description="Daily average over the well-logged days only.")
    average_needs_kcal: float | None
    average_balance_kcal: float | None
    protein_g_per_kg: float | None
    carbs_g_per_kg: float | None


def week(
    meals: list[Meal],
    workouts: list[Workout],
    profile: Profile,
    end: datetime.date,
    now: datetime.datetime | None = None,
) -> WeekSummary:
    """The 7 days ending on ``end`` (inclusive).

    Averages only count well-logged days, as in Bob: a day with a single entry says more about the log than about
    the eating. Pass yesterday as ``end`` for a week of complete days.
    """
    dates = [end - datetime.timedelta(days=i) for i in range(WEEK_DAYS - 1, -1, -1)]
    days = [day(meals, workouts, profile, d, now) for d in dates]
    good = [d for d in days if d.meals >= MIN_MEALS_TO_JUDGE_INTAKE]
    average = (
        Nutrients(**{k: round(sum(getattr(d.totals, k) or 0 for d in good) / len(good), 1) for k in NUTRIENTS})
        if good
        else None
    )
    day_needs = [d.needs.total_kcal for d in good if d.needs]
    avg_needs = round(sum(day_needs) / len(day_needs), 1) if good and len(day_needs) == len(good) else None
    w = profile.weight_kg
    return WeekSummary(
        start=dates[0],
        end=end,
        days=days,
        well_logged_days=len(good),
        average=average,
        average_needs_kcal=avg_needs,
        average_balance_kcal=round(average.kcal - avg_needs, 1)
        if average and average.kcal is not None and avg_needs
        else None,
        protein_g_per_kg=round((average.protein_g or 0) / w, 2) if average and w else None,
        carbs_g_per_kg=round((average.carbs_g or 0) / w, 2) if average and w else None,
    )
