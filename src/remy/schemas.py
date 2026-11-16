"""Request and response models of the HTTP API.

They live in the library (pydantic only) so that the service and the typed client share them.
"""

import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from remy.checks import FindingCode
from remy.energy import Profile, Sex
from remy.foods import Lang, Nutrients
from remy.importers.bob import Problem
from remy.nutrients import ItemWarning, MealItem, MealItemIn
from remy.slots import Slot
from remy.summary import DaySummary, WeekSummary

MAX_TEXT = 200
MAX_ITEMS = 50


def _valid_timezone(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown IANA time zone: {v!r}") from e
    return v


# --- foods and nutrients ------------------------------------------------------------------------------------------


class FoodOut(BaseModel):
    code: str
    name: str = Field(description="Name in the requested language (French where no English name exists).")
    name_fr: str
    name_en: str | None = None
    brand: str | None = None
    source: str = Field(description="ciqual, off (Open Food Facts) or recipe.")
    per_100g: Nutrients
    portion_g: float | None = Field(default=None, description="Weight of one portion, if the food has one.")
    attribution: str | None = Field(
        default=None, description="Credit to show when using this food, if its source asks."
    )


class FoodSearchOut(BaseModel):
    query: str
    lang: Lang
    foods: list[FoodOut]


class NutrientsIn(BaseModel):
    items: list[MealItemIn] = Field(max_length=MAX_ITEMS)
    lang: Lang | None = None


# --- users and keys -----------------------------------------------------------------------------------------------


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    timezone: str = "Europe/Paris"
    lang: Lang = "fr"

    _tz = field_validator("timezone")(_valid_timezone)


class UserOut(BaseModel):
    id: int
    name: str
    timezone: str
    lang: Lang
    created_at: datetime.datetime


class ApiKeyIn(BaseModel):
    label: str = Field(default="", max_length=64)


class ApiKeyOut(BaseModel):
    id: int
    user_id: int
    prefix: str = Field(description="First characters of the key, to tell keys apart.")
    label: str
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="The full key. Shown once: only its hash is stored.")


class UserCreated(BaseModel):
    user: UserOut
    api_key: ApiKeyCreated


# --- profile ------------------------------------------------------------------------------------------------------


class Goals(BaseModel):
    """Personal targets. Stored and returned for clients; they do not change Remy's reference ranges."""

    target_weight_kg: float | None = Field(default=None, ge=30, le=250)
    protein_g_per_kg: float | None = Field(default=None, ge=0.5, le=4)


class ProfileIn(Profile):
    """Profile fields. With PUT, omitted fields are cleared (time zone and language are kept); with PATCH, only the
    fields sent change."""

    timezone: str | None = None
    lang: Lang | None = None
    goals: Goals | None = None

    _tz = field_validator("timezone")(_valid_timezone)


class ProfileOut(BaseModel):
    weight_kg: float | None
    height_cm: float | None
    birth_year: int | None
    sex: Sex | None
    activity_factor: float | None
    timezone: str
    lang: Lang
    goals: Goals
    missing: list[str] = Field(description="Fields still needed to compute energy needs.")
    bmr_kcal: float | None
    rest_day_needs_kcal: float | None = Field(description="BMR × activity factor: the needs of a day without workout.")


# --- meals --------------------------------------------------------------------------------------------------------


class MealIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT, description="What was eaten, as the user would say it.")
    at: datetime.datetime | None = Field(
        default=None,
        description="When it was eaten. Without offset: the user's local time. Default: now.",
    )
    items: list[MealItemIn] | None = Field(default=None, max_length=MAX_ITEMS)
    nutrients: Nutrients | None = Field(
        default=None, description="Client estimate, used only when no item could be matched."
    )
    slot: Slot | None = Field(default=None, description="Default: the slot of the local time.")
    source: str = Field(default="api", max_length=40)
    repeat: bool = Field(default=False, description="The user ate the same dish again: not a duplicate.")
    skipped: bool = Field(default=False, description="The user says they skipped this meal.")
    external_id: str | None = Field(
        default=None, max_length=100, description="Client id: posting the same one again returns the stored meal."
    )

    @field_validator("text", mode="before")
    @classmethod
    def _squash_spaces(cls, v: object) -> object:
        return " ".join(v.split()) if isinstance(v, str) else v


class MealPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    at: datetime.datetime | None = None
    items: list[MealItemIn] | None = Field(default=None, max_length=MAX_ITEMS)
    nutrients: Nutrients | None = None
    slot: Slot | None = None
    repeat: bool | None = None
    skipped: bool | None = None


class MealOut(BaseModel):
    id: int
    date: datetime.date
    time: str = Field(description="Local time, HH:MM.")
    slot: Slot
    text: str
    nutrients: Nutrients
    items: list[MealItem]
    source: str
    repeat: bool
    skipped: bool
    external_id: str | None = None
    created_at: datetime.datetime


class MealLogged(BaseModel):
    meal: MealOut
    created: bool = Field(description="False when an existing meal with the same external_id was returned.")
    possible_duplicate: MealOut | None = Field(
        description="A meal with the same dish within 3 hours. The meal was stored anyway: the client decides."
    )
    warnings: list[ItemWarning]


# --- workouts -----------------------------------------------------------------------------------------------------


class WorkoutIn(BaseModel):
    date: datetime.date
    kind: str = Field(default="run", max_length=40)
    kcal: float | None = Field(default=None, ge=0, le=10000, description="Device calories; preferred when given.")
    km: float | None = Field(default=None, ge=0, le=500)
    minutes: float | None = Field(default=None, ge=0, le=2000)
    external_id: str | None = Field(
        default=None, max_length=100, description="Client id: posting the same one again updates the workout."
    )


class WorkoutOut(WorkoutIn):
    id: int
    kcal_counted: float = Field(description="Energy counted in the day's needs.")


# --- days, weeks, slot checks -------------------------------------------------------------------------------------


class FindingOut(BaseModel):
    """A finding (see :class:`remy.checks.Finding`) with its message in the requested language."""

    code: FindingCode
    date: datetime.date
    slot: Slot | None = None
    meal_ids: list[int | str] = Field(default_factory=list)
    values: dict[str, float | int | str] = Field(default_factory=dict)
    message: str


class DayOut(DaySummary):
    timezone: str
    log_issues: list[FindingOut]
    anomalies: list[FindingOut]
    meals_logged: list[MealOut]
    workouts: list[WorkoutOut]


class WeekOut(WeekSummary):
    days: list[DayOut]


CheckSlot = Literal["breakfast", "lunch", "snack", "dinner", "day"]
CheckStatus = Literal["asked", "skipped", "answered", "checked"]


class SlotCheckIn(BaseModel):
    status: CheckStatus


class SlotCheckOut(BaseModel):
    date: datetime.date
    slot: CheckSlot
    status: CheckStatus | None = Field(description="None: nothing recorded for this slot.")
    updated_at: datetime.datetime | None = None


# --- recipes ------------------------------------------------------------------------------------------------------


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    items: list[MealItemIn] = Field(min_length=1, max_length=MAX_ITEMS, description="Ingredients, with their weight.")
    portions: float = Field(default=1, gt=0, le=100, description="How many portions the recipe makes.")
    yield_g: float | None = Field(
        default=None, gt=0, le=50000, description="Weight of the cooked dish; default: the weight of the ingredients."
    )
    external_id: str | None = Field(
        default=None,
        max_length=100,
        description="Client id (e.g. the groceries manager's): posting it again updates the recipe.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _squash_spaces(cls, v: object) -> object:
        return " ".join(v.split()) if isinstance(v, str) else v


class RecipeOut(BaseModel):
    id: int
    code: str = Field(description="Food code to use in meal items: recipe:<id>.")
    name: str
    external_id: str | None = None
    portions: float
    weight_g: float = Field(description="Weight of the dish (yield_g, or the ingredients' weight).")
    portion_g: float
    items: list[MealItem]
    totals: Nutrients = Field(description="The whole dish.")
    per_portion: Nutrients
    per_100g: Nutrients
    created_at: datetime.datetime
    updated_at: datetime.datetime


class RecipeSaved(BaseModel):
    recipe: RecipeOut
    created: bool
    warnings: list[ItemWarning]


# --- import -------------------------------------------------------------------------------------------------------


class BobStateIn(BaseModel):
    """Bob's state file (``coach_state.json``), as it is. Only ``meals``, ``profile`` and ``meal_checks`` are read."""

    model_config = ConfigDict(extra="allow")

    meals: list = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)
    meal_checks: dict = Field(default_factory=dict)


class ImportCounts(BaseModel):
    imported: int = 0
    already_present: int = Field(default=0, description="Left as they are: imported earlier, or set in Remy since.")
    invalid: int = Field(default=0, description="Entries that could not be read (see problems).")


class BobImportReport(BaseModel):
    dry_run: bool = Field(description="True: nothing was written; this is what would happen.")
    meals: ImportCounts
    meal_checks: ImportCounts
    profile_set: list[str] = Field(description="Profile fields filled from Bob's profile.")
    profile_kept: list[str] = Field(description="Profile fields already set in Remy: not overwritten.")
    problems: list[Problem]
