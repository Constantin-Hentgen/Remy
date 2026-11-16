"""Food search, barcode lookup and nutrient computation: stateless apart from the product cache."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from remy import foods, off
from remy.foods import FoodTable, Lang
from remy.nutrients import MealComputation, compute
from remy.schemas import FoodOut, FoodSearchOut, NutrientsIn
from remy.service import openfoodfacts, recipes
from remy.service.convert import food_out
from remy.service.deps import CurrentUser, Db, FoodResolver, user_lang

router = APIRouter(prefix="/v1", tags=["foods"])

Source = Literal["ciqual", "off", "recipe", "all"]


@router.get("/foods")
def search_foods(
    request: Request,
    db: Db,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Short description, e.g. 'riz blanc cuit'.")],
    lang: Lang | None = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
    source: Annotated[
        Source,
        Query(description="ciqual (default), off (Open Food Facts products already looked up), recipe (yours) or all."),
    ] = "ciqual",
) -> FoodSearchOut:
    """Candidate foods for a description, best first, with values per 100 g. The client picks one and sends its
    ``code`` back in meal items."""
    language = user_lang(user, lang)
    found = []
    if source in ("ciqual", "all"):
        found += foods.ciqual().search_scored(q, language, limit)
    if source in ("off", "all"):
        found += FoodTable(openfoodfacts.cached_foods(db)).search_scored(q, language, limit)
    if source in ("recipe", "all"):
        found += FoodTable(recipes.foods_of(db, user)).search_scored(q, language, limit)
    found.sort(key=lambda s: s[0], reverse=True)  # stable: Ciqual first on ties
    return FoodSearchOut(query=q, lang=language, foods=[food_out(f, language) for _, f in found[:limit]])


@router.get("/foods/barcode/{barcode}")
def get_barcode(request: Request, db: Db, user: CurrentUser, barcode: str, lang: Lang | None = None) -> FoodOut:
    """A packaged product by its barcode (EAN/UPC), from Open Food Facts through a local cache.

    Use the returned ``code`` (``off:<barcode>``) in meal items. 404: unknown to Open Food Facts, or without an
    energy value. 503: Open Food Facts cannot be reached and the product is not cached.
    """
    if not off.is_barcode(barcode):
        raise HTTPException(422, "a barcode is 8 to 14 digits")
    try:
        food = openfoodfacts.lookup(db, request.app.state.off, barcode)
    except openfoodfacts.OffUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no usable product with barcode {barcode}")
    return food_out(food, user_lang(user, lang))


@router.post("/nutrients")
def post_nutrients(user: CurrentUser, resolver: FoodResolver, body: NutrientsIn) -> MealComputation:
    """Per-item and total nutrients for ``[{food_code | food_query, grams | portions}]``, with warnings for unknown
    foods and invalid weights. Nothing is stored."""
    return compute(body.items, user_lang(user, body.lang), resolver=resolver)
