"""Nutrients of a meal, computed from the composition table: never guessed.

A meal is a list of items ``{food_code | food_query, grams}``. The client (often an LLM turning free text into
items) picks the food and estimates the weight; Remy looks the food up and does the arithmetic. Problems with one
item (unknown food, absurd weight) become warnings and leave the rest of the meal intact, so the client can fix just
that item.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from remy.foods import Food, FoodTable, Lang, Nutrients, ciqual

MAX_GRAMS = 2000
"""Upper bound per item. A hallucinated weight ("5000 g of pasta") must not blow up the day's balance."""

MAX_LABEL = 80


class MealItemIn(BaseModel):
    """One food of a meal, as sent by a client. ``food_code`` wins over ``food_query`` when both are given."""

    food_code: str | None = None
    food_query: str | None = None
    grams: float | None = Field(default=None, description=f"Weight eaten, in grams (0 < grams <= {MAX_GRAMS}).")

    @field_validator("food_code", "food_query", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        if v is None:
            return None
        text = " ".join(str(v).split())
        return text or None


class MealItem(BaseModel):
    """An item matched to a food, with its nutrients for the weight eaten."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="Position of the item in the request.")
    label: str = Field(description="The client's query, or the food name when only a code was given.")
    food_code: str
    food_name: str
    grams: float
    nutrients: Nutrients


WarningCode = Literal["unknown_food_code", "no_match", "invalid_grams"]


class ItemWarning(BaseModel):
    """Why an item was left out of the totals (or, for ``unknown_food_code``, matched by its query instead)."""

    model_config = ConfigDict(frozen=True)

    index: int
    code: WarningCode
    label: str
    detail: str


class MealComputation(BaseModel):
    items: list[MealItem]
    totals: Nutrients
    warnings: list[ItemWarning]


def compute(
    items: Sequence[MealItemIn | Mapping[str, object]],
    lang: Lang = "fr",
    table: FoodTable | None = None,
) -> MealComputation:
    """Per-item and total nutrients of a meal.

    Per-item values are rounded to 0.1, the total energy to the kcal (as in Bob). Unknown values (Ciqual has none)
    count as zero in the totals.
    """
    table = table or ciqual()
    out: list[MealItem] = []
    warnings: list[ItemWarning] = []
    for index, raw in enumerate(items):
        item = raw if isinstance(raw, MealItemIn) else MealItemIn.model_validate(raw)
        query = (item.food_query or "")[:MAX_LABEL]
        label = query or item.food_code or ""
        food: Food | None = table.get(item.food_code) if item.food_code else None
        if item.food_code and food is None:
            warnings.append(
                ItemWarning(
                    index=index,
                    code="unknown_food_code",
                    label=label,
                    detail=f"no food with code {item.food_code!r}"
                    + ("; matched by its query instead" if item.food_query else ""),
                )
            )
        if food is None and item.food_query:
            food = next(iter(table.search(item.food_query, lang, 1)), None)
            if food is None:
                warnings.append(ItemWarning(index=index, code="no_match", label=label, detail="no matching food"))
        if food is None:
            if not item.food_code and not item.food_query:
                warnings.append(ItemWarning(index=index, code="no_match", label=label, detail="no food given"))
            continue
        grams = item.grams or 0
        if not 0 < grams <= MAX_GRAMS:
            warnings.append(
                ItemWarning(
                    index=index,
                    code="invalid_grams",
                    label=label,
                    detail=f"{grams:g} g is outside (0, {MAX_GRAMS}] g",
                )
            )
            continue
        out.append(
            MealItem(
                index=index,
                label=query or food.name(lang),
                food_code=food.code,
                food_name=food.name(lang),
                grams=round(grams, 1),
                nutrients=food.per_100g.scaled(grams),
            )
        )
    return MealComputation(items=out, totals=Nutrients.total([i.nutrients for i in out]), warnings=warnings)
