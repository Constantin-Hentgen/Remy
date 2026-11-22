"""Food search and nutrient computation, on the Ciqual table. Stateless."""

from typing import Annotated

from fastapi import APIRouter, Query

from remy import foods
from remy.foods import Food, Lang
from remy.nutrients import MealComputation, compute
from remy.schemas import FoodOut, FoodSearchOut, NutrientsIn

router = APIRouter(prefix="/v1", tags=["foods"])


def food_out(food: Food, lang: Lang) -> FoodOut:
    return FoodOut(**food.model_dump(), name=food.name(lang))


@router.get("/foods")
def search_foods(
    q: Annotated[str, Query(min_length=1, max_length=100, description="Short description, e.g. 'riz blanc cuit'.")],
    lang: Lang = "fr",
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> FoodSearchOut:
    """Candidate foods for a description, best first, with values per 100 g."""
    return FoodSearchOut(query=q, lang=lang, foods=[food_out(f, lang) for f in foods.search(q, lang, limit)])


@router.post("/nutrients")
def post_nutrients(body: NutrientsIn) -> MealComputation:
    """Per-item and total nutrients for ``[{food_code | food_query, grams}]``, with warnings for unknown foods and
    invalid weights."""
    return compute(body.items, body.lang)
