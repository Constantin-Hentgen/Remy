"""The meal log. Remy stores what the client says was eaten, computes its nutrients and hints at duplicates."""

import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from remy.checks import find_duplicate
from remy.foods import NUTRIENTS, Nutrients
from remy.nutrients import ItemWarning, MealItemIn, compute
from remy.schemas import MealIn, MealLogged, MealOut, MealPatch
from remy.service.convert import meal_core, meal_out
from remy.service.db import MealRow, User
from remy.service.deps import CurrentUser, Db, local_now, parse_day, to_local, user_lang
from remy.slots import slot_of

router = APIRouter(prefix="/v1/me/meals", tags=["meals"])

FUTURE_TOLERANCE = datetime.timedelta(minutes=5)
"""Clock skew allowance. Beyond it a meal "in the future" is refused: the log records what was eaten, not plans."""
MAX_RANGE_DAYS = 366


def meals_between(db: Db, user: User, start: datetime.date, end: datetime.date) -> list[MealRow]:
    query = (
        select(MealRow)
        .where(MealRow.user_id == user.id, MealRow.date >= start, MealRow.date <= end)
        .order_by(MealRow.date, MealRow.time, MealRow.id)
    )
    return list(db.scalars(query))


def _own_meal(db: Db, user: User, meal_id: int) -> MealRow:
    row = db.get(MealRow, meal_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no meal {meal_id}")
    return row


def _set_nutrients(
    row: MealRow, user: User, items: list[MealItemIn] | None, estimate: Nutrients | None
) -> list[ItemWarning]:
    """Computed from the items when at least one matches; otherwise the client's estimate (as in Bob)."""
    warnings: list[ItemWarning] = []
    nutrients = estimate or Nutrients()
    stored_items: list[dict] = []
    if items:
        computed = compute(items, user_lang(user, None))
        warnings = computed.warnings
        if computed.items:
            nutrients = computed.totals
            stored_items = [i.model_dump() for i in computed.items]
    for name in NUTRIENTS:
        value = getattr(nutrients, name)
        setattr(row, name, None if value is None else max(0.0, round(value, 1)))
    row.items = stored_items
    return warnings


def _set_time(request: Request, row: MealRow, user: User, at: datetime.datetime | None) -> datetime.datetime:
    now = local_now(request, user)
    local = to_local(at, user) if at else now.replace(second=0, microsecond=0)
    if local > now + FUTURE_TOLERANCE:
        raise HTTPException(422, "meal in the future: only log what was eaten")
    row.date, row.time = local.date(), local.time()
    return local


@router.post("", status_code=status.HTTP_201_CREATED)
def log_meal(request: Request, response: Response, db: Db, user: CurrentUser, body: MealIn) -> MealLogged:
    """Log a meal. When ``items`` are given, nutrients are computed from the food table.

    The meal is always stored. ``possible_duplicate`` points at a meal with the same dish within 3 hours (unless
    ``repeat`` is true): the client decides whether to keep both or delete one.
    """
    if body.external_id:
        existing = db.scalar(select(MealRow).where(MealRow.user_id == user.id, MealRow.external_id == body.external_id))
        if existing:
            response.status_code = status.HTTP_200_OK
            return MealLogged(meal=meal_out(existing), created=False, possible_duplicate=None, warnings=[])
    row = MealRow(
        user_id=user.id,
        text=body.text,
        source=body.source,
        repeat=body.repeat,
        skipped=body.skipped,
        external_id=body.external_id,
    )
    local = _set_time(request, row, user, body.at)
    row.slot = body.slot or slot_of(local.time())
    warnings = _set_nutrients(row, user, body.items, body.nutrients)
    duplicate = None
    if not body.repeat and not body.skipped:
        day = datetime.timedelta(days=1)
        nearby = [meal_core(m) for m in meals_between(db, user, local.date() - day, local.date() + day)]
        found = find_duplicate(nearby, body.text, local)
        duplicate = meal_out(db.get(MealRow, found.id)) if found else None
    db.add(row)
    db.commit()
    return MealLogged(meal=meal_out(row), created=True, possible_duplicate=duplicate, warnings=warnings)


@router.get("")
def list_meals(
    request: Request,
    db: Db,
    user: CurrentUser,
    start: Annotated[str | None, Query(alias="from", description="First day: ISO date, today or yesterday.")] = None,
    end: Annotated[str | None, Query(alias="to", description="Last day; default: same as from.")] = None,
) -> list[MealOut]:
    """Meals between two local dates (inclusive), oldest first. Default: today."""
    today = local_now(request, user).date()
    first = parse_day(start, today) if start else today
    last = parse_day(end, today) if end else first
    start, end = first, last
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(422, f"'to' must be within {MAX_RANGE_DAYS} days of 'from'")
    return [meal_out(m) for m in meals_between(db, user, start, end)]


@router.get("/{meal_id}")
def get_meal(db: Db, user: CurrentUser, meal_id: int) -> MealOut:
    return meal_out(_own_meal(db, user, meal_id))


@router.patch("/{meal_id}")
def patch_meal(request: Request, db: Db, user: CurrentUser, meal_id: int, body: MealPatch) -> MealLogged:
    """Correct a meal: its text, time, slot, foods or flags. Sending ``items`` recomputes the nutrients."""
    row = _own_meal(db, user, meal_id)
    sent = body.model_fields_set
    if body.text is not None:
        row.text = " ".join(body.text.split())
    if body.at is not None:
        local = _set_time(request, row, user, body.at)
        row.slot = slot_of(local.time())
    if body.slot is not None:
        row.slot = body.slot
    if body.repeat is not None:
        row.repeat = body.repeat
    if body.skipped is not None:
        row.skipped = body.skipped
    warnings: list[ItemWarning] = []
    if "items" in sent or "nutrients" in sent:
        warnings = _set_nutrients(row, user, body.items, body.nutrients)
    db.commit()
    return MealLogged(meal=meal_out(row), created=False, possible_duplicate=None, warnings=warnings)


@router.delete("/{meal_id}")
def delete_meal(db: Db, user: CurrentUser, meal_id: int) -> MealOut:
    """Remove a meal (a duplicate, or one logged by mistake). Returns what was removed."""
    row = _own_meal(db, user, meal_id)
    removed = meal_out(row)
    db.delete(row)
    db.commit()
    return removed
