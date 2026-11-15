"""Meal slots: which meal a time of day belongs to, and when each main meal is over.

The boundaries are Bob's, tuned for a French eating schedule: breakfast until 10:30, lunch until 15:30, an
afternoon snack until 17:30, dinner after that (and through the night: a 01:00 meal is a late dinner, not
breakfast). A main meal counts as "missed" only once its slot is over: 10:30, 15:30, and 22:30 for dinner.
"""

import datetime
from enum import StrEnum

from remy.foods import Lang


class Slot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACK = "snack"
    DINNER = "dinner"


MAIN_MEALS: tuple[Slot, ...] = (Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER)

SLOT_ENDS: dict[Slot, datetime.time] = {
    Slot.BREAKFAST: datetime.time(10, 30),
    Slot.LUNCH: datetime.time(15, 30),
    Slot.DINNER: datetime.time(22, 30),
}

LABELS: dict[Lang, dict[Slot, str]] = {
    "fr": {Slot.BREAKFAST: "petit-déjeuner", Slot.LUNCH: "déjeuner", Slot.SNACK: "collation", Slot.DINNER: "dîner"},
    "en": {Slot.BREAKFAST: "breakfast", Slot.LUNCH: "lunch", Slot.SNACK: "snack", Slot.DINNER: "dinner"},
}


def slot_of(t: datetime.time) -> Slot:
    """The meal eaten at this local time."""
    h = t.hour + t.minute / 60
    if 4 <= h < 10.5:
        return Slot.BREAKFAST
    if 10.5 <= h < 15.5:
        return Slot.LUNCH
    if 15.5 <= h < 17.5:
        return Slot.SNACK
    return Slot.DINNER


def slot_over(slot: Slot, day: datetime.date, now: datetime.datetime | None) -> bool:
    """Whether the main meal ``slot`` of ``day`` is over at local time ``now`` (``None``: the day is over)."""
    if now is None or day < now.date():
        return True
    if day > now.date():
        return False
    return slot in SLOT_ENDS and now.time() >= SLOT_ENDS[slot]
