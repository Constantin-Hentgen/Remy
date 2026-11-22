"""Recipe suggestions: what the client asks, what the model drafts, and the nutrients Remy computes for each draft.

The model invents the dishes; it never gives the numbers. Each ingredient comes with a short Ciqual-style
description and a weight, and Remy computes the nutrients from the Ciqual table, so totals are as reliable as
the weights. Ingredients that match no food are reported, not guessed.

Pure: no web stack, no Anthropic SDK. The service (:mod:`remy.service.chef`) does the model call.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from remy.foods import Lang, Nutrients
from remy.nutrients import compute

Meal = Literal["breakfast", "lunch", "dinner", "snack"]
MAX_PANTRY = 2000
MAX_NOTES = 1000


class Target(BaseModel):
    """What one serving should bring. Every field is optional."""

    kcal: float | None = Field(default=None, gt=0, le=3000)
    protein_g: float | None = Field(default=None, ge=0, le=300)
    carbs_g: float | None = Field(default=None, ge=0, le=600)
    fat_g: float | None = Field(default=None, ge=0, le=300)


class SuggestIn(BaseModel):
    pantry: str = Field(
        min_length=1,
        max_length=MAX_PANTRY,
        description="What is available to cook, in free text: '4 eggs, 200 g of rice, a can of tuna, spinach'.",
    )
    pantry_only: bool = Field(
        default=False,
        description="Use only the pantry, plus water, salt, pepper, oil and dried spices. "
        "False: a few extra ingredients may be suggested; they are flagged as missing.",
    )
    meal: Meal | None = None
    servings: int = Field(default=1, ge=1, le=12)
    count: int = Field(default=3, ge=1, le=5, description="How many recipes to suggest.")
    target: Target | None = Field(default=None, description="Nutrition target per serving.")
    notes: str | None = Field(
        default=None,
        max_length=MAX_NOTES,
        description="Anything else: time available, equipment, dislikes, training context ('long run tomorrow').",
    )
    lang: Lang = "fr"

    @field_validator("pantry", "notes", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


# --- what the model returns (structured output) -------------------------------------------------------------------


class DraftIngredient(BaseModel):
    name: str = Field(description="As shown to the cook, in the requested language: '2 oeufs', 'riz basmati'.")
    ciqual_query: str = Field(
        description="Short French description in Ciqual style, matching the state the grams are weighed in: "
        "'riz blanc cru', 'oeuf cru', 'huile d'olive', 'thon au naturel appertisé égoutté'."
    )
    grams: float = Field(description="Weight for the whole recipe, in grams, in the state described.")
    on_hand: bool = Field(description="True if it comes from the pantry or the basic staples.")


class DraftRecipe(BaseModel):
    name: str
    summary: str = Field(description="One sentence: what it is and why it fits.")
    minutes: int = Field(description="Total time, preparation and cooking.")
    servings: int
    ingredients: list[DraftIngredient]
    steps: list[str]


class Drafts(BaseModel):
    recipes: list[DraftRecipe]


# --- what Remy returns --------------------------------------------------------------------------------------------


class IngredientOut(BaseModel):
    name: str
    grams: float
    on_hand: bool
    food_code: str | None = Field(default=None, description="The Ciqual food used for the numbers; None if unmatched.")
    food_name: str | None = None
    nutrients: Nutrients | None = None


class RecipeOut(BaseModel):
    name: str
    summary: str
    minutes: int
    servings: int
    ingredients: list[IngredientOut]
    steps: list[str]
    missing: list[str] = Field(description="Ingredients that are not on hand.")
    totals: Nutrients = Field(description="The whole recipe, from Ciqual.")
    per_serving: Nutrients
    unmatched: list[str] = Field(description="Ingredients left out of the numbers: no Ciqual food or invalid weight.")


class SuggestOut(BaseModel):
    recipes: list[RecipeOut]
    target: Target | None = None
    model: str = Field(description="The model that drafted the recipes.")


def per_serving(totals: Nutrients, servings: int) -> Nutrients:
    values = {k: None if v is None else round(v / servings, 1) for k, v in totals.values().items()}
    values["kcal"] = None if values["kcal"] is None else round(values["kcal"])
    return Nutrients(**values)


def check(draft: DraftRecipe, servings: int) -> RecipeOut:
    """Computes a draft's nutrients from Ciqual. Ingredient names stay as drafted; Ciqual lookups are in French."""
    servings = draft.servings if 1 <= draft.servings <= 12 else servings
    computed = compute([{"food_query": i.ciqual_query or i.name, "grams": i.grams} for i in draft.ingredients], "fr")
    matched = {item.index: item for item in computed.items}
    ingredients = [
        IngredientOut(
            name=i.name,
            grams=round(i.grams, 1),
            on_hand=i.on_hand,
            food_code=matched[n].food_code if n in matched else None,
            food_name=matched[n].food_name if n in matched else None,
            nutrients=matched[n].nutrients if n in matched else None,
        )
        for n, i in enumerate(draft.ingredients)
    ]
    return RecipeOut(
        name=draft.name,
        summary=draft.summary,
        minutes=max(draft.minutes, 0),
        servings=servings,
        ingredients=ingredients,
        steps=draft.steps,
        missing=[i.name for i in draft.ingredients if not i.on_hand],
        totals=computed.totals,
        per_serving=per_serving(computed.totals, servings),
        unmatched=[i.name for n, i in enumerate(draft.ingredients) if n not in matched],
    )
