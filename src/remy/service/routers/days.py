"""Day and week views: intake against needs, with the findings."""

import datetime

from fastapi import APIRouter, Request

from remy import summary
from remy.foods import Lang
from remy.schemas import DayOut, WeekOut
from remy.service.convert import finding_out, meal_core, meal_out, profile_of, workout_core, workout_out
from remy.service.db import MealRow, User, WorkoutRow
from remy.service.deps import CurrentUser, Db, local_now, parse_day, user_lang
from remy.service.routers.meals import meals_between
from remy.service.routers.workouts import workouts_between
from remy.summary import DaySummary

router = APIRouter(prefix="/v1/me", tags=["days"])


def _day_out(s: DaySummary, user: User, meals: list[MealRow], workouts: list[WorkoutRow], lang: Lang) -> DayOut:
    data = s.model_dump(exclude={"log_issues", "anomalies"})
    return DayOut(
        **data,
        timezone=user.timezone,
        log_issues=[finding_out(f, lang) for f in s.log_issues],
        anomalies=[finding_out(f, lang) for f in s.anomalies],
        meals_logged=[meal_out(m) for m in meals if m.date == s.date],
        workouts=[workout_out(w, user.weight_kg) for w in workouts if w.date == s.date],
    )


@router.get("/days/{date}")
def get_day(request: Request, db: Db, user: CurrentUser, date: str, lang: Lang | None = None) -> DayOut:
    """One day: totals, needs (BMR, daily activity, workouts), balance, protein and carbs against the reference
    ranges, log issues and anomalies. ``date`` is ISO, ``today`` or ``yesterday`` (the user's)."""
    now = local_now(request, user)
    day = parse_day(date, now.date())
    meals = meals_between(db, user, day, day)
    workouts = workouts_between(db, user, day, day)
    s = summary.day([meal_core(m) for m in meals], [workout_core(w) for w in workouts], profile_of(user), day, now)
    return _day_out(s, user, meals, workouts, user_lang(user, lang))


@router.get("/weeks/{date}")
def get_week(request: Request, db: Db, user: CurrentUser, date: str, lang: Lang | None = None) -> WeekOut:
    """The 7 days ending on ``date`` (inclusive), with averages over the well-logged days (at least 2 meals).
    Ask for ``yesterday`` to get a week of complete days."""
    now = local_now(request, user)
    end = parse_day(date, now.date())
    start = end - datetime.timedelta(days=summary.WEEK_DAYS - 1)
    meals = meals_between(db, user, start, end)
    workouts = workouts_between(db, user, start, end)
    w = summary.week([meal_core(m) for m in meals], [workout_core(x) for x in workouts], profile_of(user), end, now)
    language = user_lang(user, lang)
    return WeekOut(
        **w.model_dump(exclude={"days"}), days=[_day_out(d, user, meals, workouts, language) for d in w.days]
    )
