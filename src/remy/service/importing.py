"""Import of Bob's state into a user's data: used by ``POST /v1/me/import/bob`` and ``remy import bob``.

Importing twice changes nothing: meals carry an ``external_id`` (``bob:meal:<id>``), existing slot checks are left
alone, and profile fields already set in Remy are not overwritten.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from remy.importers import bob
from remy.schemas import BobImportReport, ImportCounts
from remy.service.db import MealRow, SlotCheckRow, User


def import_bob(db: Session, user: User, state: Mapping[str, Any], dry_run: bool = False) -> BobImportReport:
    """Write Bob's meals, profile and meal checks for ``user``. With ``dry_run`` nothing is kept."""
    parsed = bob.parse(state)
    meals = ImportCounts(invalid=sum(p.section == "meals" for p in parsed.problems))
    checks = ImportCounts(invalid=sum(p.section == "meal_checks" for p in parsed.problems))

    known = set(
        db.scalars(select(MealRow.external_id).where(MealRow.user_id == user.id, MealRow.external_id.like("bob:%")))
    )
    for meal in parsed.meals:
        if meal.external_id in known:
            meals.already_present += 1
            continue
        db.add(
            MealRow(
                user_id=user.id,
                external_id=meal.external_id,
                date=meal.date,
                time=meal.time,
                slot=meal.slot.value,
                text=meal.text,
                **meal.nutrients.values(),
                items=[i.model_dump() for i in meal.items],
                source=meal.source,
                repeat=meal.repeat,
                skipped=meal.skipped,
            )
        )
        meals.imported += 1

    for check in parsed.checks:
        if db.get(SlotCheckRow, (user.id, check.date, check.slot)):
            checks.already_present += 1
            continue
        db.add(SlotCheckRow(user_id=user.id, date=check.date, slot=check.slot, status=check.status))
        checks.imported += 1

    profile_set, profile_kept = [], []
    for name, value in parsed.profile.items():
        if getattr(user, name) is None:
            setattr(user, name, value.value if name == "sex" else value)
            profile_set.append(name)
        else:
            profile_kept.append(name)

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return BobImportReport(
        dry_run=dry_run,
        meals=meals,
        meal_checks=checks,
        profile_set=profile_set,
        profile_kept=profile_kept,
        problems=parsed.problems,
    )
