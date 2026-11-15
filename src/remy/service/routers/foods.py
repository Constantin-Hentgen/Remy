"""Food search and nutrient computation: stateless, but still behind an API key."""

from typing import Annotated

from fastapi import APIRouter, Query

from remy import foods
from remy.foods import Lang
from remy.nutrients import MealComputation, compute
from remy.schemas import FoodSearchOut, NutrientsIn
from remy.service.convert import food_out
from remy.service.deps import CurrentUser, user_lang

router = APIRouter(prefix="/v1", tags=["foods"])


@router.get("/foods")
def search_foods(
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Short description, e.g. 'riz blanc cuit'.")],
    lang: Lang | None = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> FoodSearchOut:
    """Candidate foods for a description, best first, with values per 100 g. The client picks one and sends its
    ``code`` back in meal items."""
    language = user_lang(user, lang)
    return FoodSearchOut(
        query=q, lang=language, foods=[food_out(f, language) for f in foods.search(q, language, limit)]
    )


@router.post("/nutrients")
def post_nutrients(user: CurrentUser, body: NutrientsIn) -> MealComputation:
    """Per-item and total nutrients for ``[{food_code | food_query, grams}]``, with warnings for unknown foods and
    invalid weights. Nothing is stored."""
    return compute(body.items, user_lang(user, body.lang))
