"""Recipes as foods: a user's dish, resolved to ingredients once, then logged by portion or by gram.

A recipe's code is ``recipe:<id>``. Its values per 100 g come from the totals over the dish's weight, and a portion
weighs ``weight / portions``. A meal keeps what it was logged with, so editing or deleting a recipe never changes the
past.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from remy.foods import NUTRIENTS, Food, Lang, Nutrients
from remy.nutrients import MealComputation, MealItem, Resolver, compute
from remy.schemas import RecipeIn, RecipeOut
from remy.service.db import RecipeRow, User, utcnow

SOURCE = "recipe"
CODE_PREFIX = "recipe:"


def code_of(recipe_id: int) -> str:
    return f"{CODE_PREFIX}{recipe_id}"


def id_of(code: str) -> int | None:
    head, _, tail = code.partition(":")
    return int(tail) if head == SOURCE and tail.isdigit() else None


def weight_g(row: RecipeRow) -> float:
    return row.yield_g or sum(i["grams"] for i in row.ingredients)


def totals_of(row: RecipeRow) -> Nutrients:
    return Nutrients(**{k: getattr(row, k) for k in NUTRIENTS})


def _scaled(totals: Nutrients, factor: float) -> Nutrients:
    return Nutrients(**{k: None if v is None else round(v * factor, 2) for k, v in totals.values().items()})


def per_100g(row: RecipeRow) -> Nutrients:
    return _scaled(totals_of(row), 100 / weight_g(row))


def food_of(row: RecipeRow) -> Food:
    return Food(
        code=code_of(row.id),
        name_fr=row.name,
        source=SOURCE,
        per_100g=per_100g(row),
        portion_g=round(weight_g(row) / row.portions, 1),
    )


def out(row: RecipeRow) -> RecipeOut:
    food = food_of(row)
    return RecipeOut(
        id=row.id,
        code=food.code,
        name=row.name,
        external_id=row.external_id,
        portions=row.portions,
        weight_g=round(weight_g(row), 1),
        portion_g=food.portion_g or 0,
        items=[MealItem(**i) for i in row.ingredients],
        totals=totals_of(row),
        per_portion=_scaled(totals_of(row), 1 / row.portions),
        per_100g=food.per_100g,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def own(db: Session, user: User, recipe_id: int) -> RecipeRow | None:
    row = db.get(RecipeRow, recipe_id)
    return row if row and row.user_id == user.id else None


def foods_of(db: Session, user: User) -> list[Food]:
    """The user's recipes as foods (what ``GET /v1/foods?source=recipe`` searches)."""
    return [
        food_of(r) for r in db.scalars(select(RecipeRow).where(RecipeRow.user_id == user.id).order_by(RecipeRow.id))
    ]


def resolver(db: Session, user: User) -> Callable[[str], Food | None]:
    """For :func:`remy.nutrients.compute`: resolves the user's ``recipe:<id>`` codes."""

    def resolve(code: str) -> Food | None:
        recipe_id = id_of(code)
        row = own(db, user, recipe_id) if recipe_id is not None else None
        return food_of(row) if row else None

    return resolve


def combine(*resolvers: Callable[[str], Food | None]) -> Resolver:
    """The first resolver that knows the code wins; each one only answers to its own prefix."""

    def resolve(code: str) -> Food | None:
        for r in resolvers:
            if food := r(code):
                return food
        return None

    return resolve


def fill(row: RecipeRow, body: RecipeIn, computed: MealComputation) -> None:
    """Set the row from a request and its computed ingredients."""
    row.name = body.name
    row.external_id = body.external_id
    row.portions = body.portions
    row.yield_g = body.yield_g
    row.ingredients = [i.model_dump() for i in computed.items]
    for name in NUTRIENTS:
        setattr(row, name, getattr(computed.totals, name))
    row.updated_at = utcnow()


def compute_ingredients(body: RecipeIn, lang: Lang, ingredient_resolver: Resolver) -> MealComputation:
    """Ingredients are Ciqual or Open Food Facts foods: a recipe cannot contain another recipe."""
    return compute(body.items, lang, resolver=ingredient_resolver)
