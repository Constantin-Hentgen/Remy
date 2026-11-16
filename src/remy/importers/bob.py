"""Read the nutrition part of Bob's state file (``/data/coach_state.json``): ``meals``, ``profile``, ``meal_checks``.

Pure parsing, with no database: it turns what Bob stored into what Remy stores, and lists what it cannot read instead
of failing on it. Bob's format (``bob/memory.py``):

- ``meals``: ``{id, date "YYYY-MM-DD", time "HH:MM", slot, text, kcal, protein_g, carbs_g, fat_g, fiber_g, sugars_g,
  salt_g, items: [{food, code, ciqual, grams, <nutrients>}], source, repeat?}``. Dates and times are already local.
  A skipped meal is a meal whose text starts with ``rien (`` ("rien (déjeuner sauté)"), with zero values.
- ``profile``: ``{weight_kg, height_cm, birth_year, sex}``.
- ``meal_checks``: ``{"YYYY-MM-DD <slot>": "asked" | "skipped" | "answered" | "checked"}``, where the slot is one of
  Bob's meal names, or ``nutrition`` for the evening recap.

Bob's values are kept as they are (its totals were rounded to whole kcal and grams): the history looks the same
in Remy as it did in Bob.
"""

import datetime
from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, ValidationError

from remy.energy import Profile
from remy.foods import NUTRIENTS, Nutrients
from remy.nutrients import MealItem
from remy.slots import Slot, slot_of

SKIPPED_PREFIX = "rien ("
"""Bob's convention for "I skipped this meal": the text of the entry."""

SOURCE = "bob"

_SLOTS = {
    "petit-déjeuner": Slot.BREAKFAST,
    "déjeuner": Slot.LUNCH,
    "collation": Slot.SNACK,
    "goûter": Slot.SNACK,
    "dîner": Slot.DINNER,
}
CheckStatus = Literal["asked", "skipped", "answered", "checked"]
_CHECK_STATUSES = frozenset(get_args(CheckStatus))
_CHECK_SLOTS = {**{k: v.value for k, v in _SLOTS.items()}, "nutrition": "day"}
MAX_TEXT = 200


class Problem(BaseModel):
    """Something in the file that could not be imported."""

    section: Literal["meals", "profile", "meal_checks"]
    ref: str = Field(description="Which entry: a meal id, a profile field, a check key.")
    detail: str


class BobMeal(BaseModel):
    """A meal of Bob's log, as Remy stores it. ``external_id`` makes importing twice harmless."""

    external_id: str
    date: datetime.date
    time: datetime.time
    slot: Slot
    text: str
    nutrients: Nutrients
    items: list[MealItem]
    source: str
    repeat: bool
    skipped: bool


class BobCheck(BaseModel):
    date: datetime.date
    slot: Literal["breakfast", "lunch", "snack", "dinner", "day"]
    status: CheckStatus


class BobState(BaseModel):
    """What was read from the file."""

    meals: list[BobMeal] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict, description="Valid profile fields, as Remy names them.")
    checks: list[BobCheck] = Field(default_factory=list)
    problems: list[Problem] = Field(default_factory=list)


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _nutrients(values: Mapping[str, Any]) -> Nutrients:
    return Nutrients(**{k: _number(values.get(k)) for k in NUTRIENTS})


def _items(raw: object) -> list[MealItem]:
    """Bob's weighed foods, with the nutrient values it computed. Entries that do not make sense are dropped."""
    out: list[MealItem] = []
    for position, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, Mapping):
            continue
        grams, code = _number(item.get("grams")), str(item.get("code") or "").strip()
        if not grams or grams <= 0 or not code:
            continue
        name = str(item.get("ciqual") or item.get("food") or code)
        out.append(
            MealItem(
                index=position,
                label=str(item.get("food") or name)[:80],
                food_code=code,
                food_name=name,
                grams=round(grams, 1),
                nutrients=_nutrients(item),
            )
        )
    return out


def _meal(raw: Mapping[str, Any]) -> BobMeal:
    """One meal; raises ``ValueError`` (or a pydantic error) when the entry cannot be read."""
    if raw.get("id") in (None, ""):
        raise ValueError("no id")
    text = " ".join(str(raw.get("text") or "").split())[:MAX_TEXT]
    if not text:
        raise ValueError("empty text")
    day = datetime.date.fromisoformat(str(raw.get("date")))
    time = datetime.time.fromisoformat(str(raw.get("time")))
    slot = _SLOTS.get(str(raw.get("slot") or "").lower()) or slot_of(time)
    return BobMeal(
        external_id=f"bob:meal:{raw['id']}",
        date=day,
        time=time.replace(second=0, microsecond=0),
        slot=slot,
        text=text,
        nutrients=_nutrients(raw),
        items=_items(raw.get("items")),
        source=str(raw.get("source") or SOURCE)[:40],
        repeat=bool(raw.get("repeat")),
        skipped=text.lower().startswith(SKIPPED_PREFIX),
    )


def _check(key: str, status: object) -> BobCheck:
    day, _, slot = str(key).partition(" ")
    if status not in _CHECK_STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if slot not in _CHECK_SLOTS:
        raise ValueError(f"unknown slot {slot!r}")
    return BobCheck(date=datetime.date.fromisoformat(day), slot=_CHECK_SLOTS[slot], status=status)  # type: ignore[arg-type]


def parse(state: Mapping[str, Any]) -> BobState:
    """Meals, profile and meal checks of a Bob state (the parsed JSON file). Unreadable entries become problems."""
    result = BobState()
    seen: set[str] = set()

    meals = state.get("meals")
    for position, raw in enumerate(meals if isinstance(meals, list) else []):
        ref = str(raw.get("id", position)) if isinstance(raw, Mapping) else str(position)
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("not an object")
            meal = _meal(raw)
        except (ValueError, ValidationError) as e:
            result.problems.append(Problem(section="meals", ref=ref, detail=str(e).splitlines()[0]))
            continue
        if meal.external_id in seen:
            result.problems.append(Problem(section="meals", ref=ref, detail="duplicate id in the file"))
            continue
        seen.add(meal.external_id)
        result.meals.append(meal)

    profile = state.get("profile")
    for name in ("weight_kg", "height_cm", "birth_year", "sex"):
        value = profile.get(name) if isinstance(profile, Mapping) else None
        if value in (None, ""):
            continue
        try:
            checked = Profile(**{name: value})
        except ValidationError as e:
            result.problems.append(Problem(section="profile", ref=name, detail=e.errors()[0]["msg"]))
            continue
        result.profile[name] = getattr(checked, name)

    checks = state.get("meal_checks")
    for key, status in checks.items() if isinstance(checks, Mapping) else []:
        try:
            result.checks.append(_check(key, status))
        except ValueError as e:
            result.problems.append(Problem(section="meal_checks", ref=str(key), detail=str(e)))
    return result
