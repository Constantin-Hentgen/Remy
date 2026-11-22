"""Request and response models of the HTTP API.

They live in the library (pydantic only) so that the service and the typed client share them.
"""

from pydantic import BaseModel, Field

from remy.foods import Lang, Nutrients
from remy.nutrients import MealItemIn

MAX_ITEMS = 50


class FoodOut(BaseModel):
    code: str = Field(description="Ciqual code, to send back as food_code.")
    name: str = Field(description="Name in the requested language.")
    name_fr: str
    name_en: str | None = None
    per_100g: Nutrients


class FoodSearchOut(BaseModel):
    query: str
    lang: Lang
    foods: list[FoodOut]


class NutrientsIn(BaseModel):
    items: list[MealItemIn] = Field(max_length=MAX_ITEMS)
    lang: Lang = "fr"
