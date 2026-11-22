"""Recipe suggestions from what is on hand. Nothing is stored."""

from fastapi import APIRouter, HTTPException, Request, status

from remy.service.chef import Chef, ChefUnavailable
from remy.suggestions import SuggestIn, SuggestOut, check

router = APIRouter(prefix="/v1", tags=["suggestions"])


@router.post("/suggest")
def suggest(request: Request, body: SuggestIn) -> SuggestOut:
    """Recipes built from the pantry, with nutrients computed from Ciqual for each one.

    The model drafts the dishes and the weights; the numbers come from the Ciqual table. 503 when the service has
    no Anthropic API key or the model cannot answer.
    """
    chef: Chef | None = request.app.state.chef
    if chef is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "suggestions need ANTHROPIC_API_KEY on the server")
    try:
        drafts = chef.draft(body)
    except ChefUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    recipes = [check(d, body.servings) for d in drafts.recipes[: body.count]]
    return SuggestOut(recipes=recipes, target=body.target, model=chef.model)
