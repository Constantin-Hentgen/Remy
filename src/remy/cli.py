"""The ``remy`` command: run the HTTP service, or ask for recipes from the terminal (needs the ``server`` extra)."""

import argparse
import sys
from collections.abc import Sequence

from remy.suggestions import RecipeOut, SuggestOut


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remy", description="Remy: nutrition for endurance athletes.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    suggest = sub.add_parser("suggest", help="suggest recipes from what you have (needs ANTHROPIC_API_KEY)")
    suggest.add_argument("pantry", help="what you have to cook, e.g. '4 eggs, rice, spinach, feta'")
    suggest.add_argument("--meal", choices=["breakfast", "lunch", "dinner", "snack"])
    suggest.add_argument("--servings", type=int, default=1)
    suggest.add_argument("--count", type=int, default=3)
    suggest.add_argument("--kcal", type=float, help="target per serving")
    suggest.add_argument("--protein", type=float, help="target grams of protein per serving")
    suggest.add_argument("--notes", help="time, equipment, dislikes, training context")
    suggest.add_argument("--pantry-only", action="store_true", help="use nothing but the pantry and staples")
    suggest.add_argument("--lang", choices=["fr", "en"], default="fr")
    return parser


def _fmt(value: float | None, unit: str) -> str:
    return "?" if value is None else f"{value:g}{unit}"


def render(recipe: RecipeOut) -> str:
    """A recipe as plain text for the terminal."""
    s = recipe.per_serving
    lines = [
        f"## {recipe.name} ({recipe.minutes} min, {recipe.servings} serving{'s' if recipe.servings > 1 else ''})",
        recipe.summary,
        f"Per serving: {_fmt(s.kcal, ' kcal')}, protein {_fmt(s.protein_g, ' g')}, carbs {_fmt(s.carbs_g, ' g')}, "
        f"fat {_fmt(s.fat_g, ' g')}",
        "",
    ]
    lines += [f"- {i.grams:g} g {i.name}" + ("" if i.on_hand else "  (to buy)") for i in recipe.ingredients]
    lines += [""] + [f"{n}. {step}" for n, step in enumerate(recipe.steps, 1)]
    if recipe.unmatched:
        lines += ["", f"Not counted in the numbers: {', '.join(recipe.unmatched)}"]
    return "\n".join(lines)


def _suggest(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from remy.service.chef import ChefUnavailable, ClaudeChef
    from remy.service.settings import get_settings
    from remy.suggestions import SuggestIn, Target, check

    settings = get_settings()
    if settings.anthropic_api_key is None:
        print("remy: set ANTHROPIC_API_KEY to get suggestions", file=sys.stderr)
        return 1
    try:
        target = Target(kcal=args.kcal, protein_g=args.protein) if args.kcal or args.protein else None
        request = SuggestIn(pantry=args.pantry, meal=args.meal, servings=args.servings, count=args.count,
                            target=target, notes=args.notes, pantry_only=args.pantry_only, lang=args.lang)  # fmt: skip
    except ValidationError as e:
        print(f"remy: {e.errors()[0]['loc'][0]}: {e.errors()[0]['msg']}", file=sys.stderr)
        return 1
    chef = ClaudeChef(settings.anthropic_api_key.get_secret_value(), settings.remy_model)
    try:
        drafts = chef.draft(request)
    except ChefUnavailable as e:
        print(f"remy: {e}", file=sys.stderr)
        return 1
    out = SuggestOut(recipes=[check(d, request.servings) for d in drafts.recipes[: request.count]], model=chef.model)
    print("\n\n".join(render(r) for r in out.recipes))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        import uvicorn
    except ImportError as e:  # pragma: no cover - depends on the installation
        print(f"remy: the command line needs the 'server' extra ({e})", file=sys.stderr)
        return 2
    if args.command == "suggest":
        return _suggest(args)
    uvicorn.run("remy.service.app:create_app", factory=True, host=args.host, port=args.port, access_log=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
