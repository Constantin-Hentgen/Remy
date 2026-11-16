"""Recipes: a user's dishes, usable as foods (``recipe:<id>``) and loggable by portion."""

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from remy.schemas import RecipeIn, RecipeOut, RecipeSaved
from remy.service import openfoodfacts, recipes
from remy.service.db import RecipeRow
from remy.service.deps import CurrentUser, Db, user_lang

router = APIRouter(prefix="/v1/me/recipes", tags=["recipes"])


def _save(request: Request, db: Db, user: CurrentUser, row: RecipeRow, body: RecipeIn, created: bool) -> RecipeSaved:
    off_only = openfoodfacts.resolver(db, request.app.state.off)
    computed = recipes.compute_ingredients(body, user_lang(user, None), off_only)
    if not computed.items:
        raise HTTPException(
            422, "no ingredient could be matched: " + "; ".join(f"{w.label}: {w.detail}" for w in computed.warnings)
        )
    if body.external_id:
        clash = db.scalar(
            select(RecipeRow.id).where(
                RecipeRow.user_id == user.id, RecipeRow.external_id == body.external_id, RecipeRow.id != (row.id or 0)
            )
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"external_id {body.external_id!r} belongs to recipe {clash}")
    recipes.fill(row, body, computed)
    if created:
        db.add(row)
    db.commit()
    return RecipeSaved(recipe=recipes.out(row), created=created, warnings=computed.warnings)


@router.post("", status_code=status.HTTP_201_CREATED)
def post_recipe(request: Request, response: Response, db: Db, user: CurrentUser, body: RecipeIn) -> RecipeSaved:
    """Create a recipe from ingredients (``[{food_code | food_query, grams}]``) and a number of portions.

    With an ``external_id`` already used by one of your recipes, that recipe is replaced (status 200), so a client
    can safely push its recipes again. Ingredients that cannot be matched come back as ``warnings`` and are left out:
    check them before relying on the numbers.
    """
    existing = None
    if body.external_id:
        existing = db.scalar(
            select(RecipeRow).where(RecipeRow.user_id == user.id, RecipeRow.external_id == body.external_id)
        )
    if existing:
        response.status_code = status.HTTP_200_OK
        return _save(request, db, user, existing, body, created=False)
    return _save(request, db, user, RecipeRow(user_id=user.id), body, created=True)


@router.get("")
def list_recipes(
    db: Db, user: CurrentUser, external_id: str | None = Query(default=None, max_length=100)
) -> list[RecipeOut]:
    """Your recipes, oldest first; ``external_id`` finds the one a client pushed under that id."""
    query = select(RecipeRow).where(RecipeRow.user_id == user.id).order_by(RecipeRow.id)
    if external_id:
        query = query.where(RecipeRow.external_id == external_id)
    return [recipes.out(r) for r in db.scalars(query)]


def _own(db: Db, user: CurrentUser, recipe_id: int) -> RecipeRow:
    row = recipes.own(db, user, recipe_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no recipe {recipe_id}")
    return row


@router.get("/{recipe_id}")
def get_recipe(db: Db, user: CurrentUser, recipe_id: int) -> RecipeOut:
    return recipes.out(_own(db, user, recipe_id))


@router.put("/{recipe_id}")
def put_recipe(request: Request, db: Db, user: CurrentUser, recipe_id: int, body: RecipeIn) -> RecipeSaved:
    """Replace a recipe. Meals already logged keep the values they were logged with."""
    return _save(request, db, user, _own(db, user, recipe_id), body, created=False)


@router.delete("/{recipe_id}")
def delete_recipe(db: Db, user: CurrentUser, recipe_id: int) -> RecipeOut:
    """Delete a recipe. Meals already logged are not affected."""
    row = _own(db, user, recipe_id)
    removed = recipes.out(row)
    db.delete(row)
    db.commit()
    return removed
