"""The model call behind recipe suggestions: Claude drafts the recipes, Remy computes their nutrients.

Only the request's own content is sent to Anthropic (pantry, meal, servings, target, notes). Nothing identifies the
caller, and nothing is stored or logged.
"""

import json
import logging
from typing import Protocol

import anthropic

from remy.suggestions import Drafts, SuggestIn

logger = logging.getLogger("remy.chef")

DEFAULT_MODEL = "claude-opus-5-5"
TIMEOUT_S = 120.0
MAX_TOKENS = 16000

SYSTEM = """\
You are the cook behind Remy, a nutrition service for endurance athletes. From what the athlete has on hand, you \
suggest recipes that are good to eat, realistic for a home kitchen, and fit for training.

Rules:
- Build each recipe around the pantry. Water, salt, pepper, cooking oil and dried spices are always available.
- When pantry_only is true, use nothing else. Otherwise you may add a few common ingredients; mark them \
on_hand: false.
- Respect the meal, the servings, the notes and, when given, the nutrition target per serving: aim for it with \
the quantities, and favour carbohydrates before long or hard training and protein after.
- Give every ingredient a weight in grams for the whole recipe, in the state it is weighed (dry pasta, raw \
chicken, cooked lentils from a can, drained). Estimate counted items (2 eggs = 110 g).
- ciqual_query is a short French description in the style of the Ciqual food table, matching that state: \
"riz blanc cru", "pâtes sèches crues", "oeuf cru", "blanc de poulet cru", "huile d'olive", "lentilles cuites", \
"thon au naturel égoutté". One food per ingredient; no brands.
- Write names, summaries and steps in the requested language. Steps are short and concrete.
- Do not state nutrient numbers anywhere: Remy computes them from the weights.
- Make the recipes different from each other."""


class ChefUnavailable(Exception):
    """No model access (no key), or the model could not answer."""


class Chef(Protocol):
    model: str

    def draft(self, request: SuggestIn) -> Drafts: ...


def brief(request: SuggestIn) -> str:
    """The user message: the request as JSON, so free text cannot pass for instructions about the format."""
    payload = request.model_dump(mode="json", exclude_none=True, exclude={"lang"})
    language = "French" if request.lang == "fr" else "English"
    return f"Suggest {request.count} recipes, written in {language}.\n\n{json.dumps(payload, ensure_ascii=False)}"


class ClaudeChef:
    """Drafts recipes with the Anthropic API (structured output, adaptive thinking, server-side fallback)."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None) -> None:
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=2)

    def draft(self, request: SuggestIn) -> Drafts:
        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                messages=[{"role": "user", "content": brief(request)}],
                output_format=Drafts,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as e:
            logger.warning("model call failed: HTTP %s", e.status_code)
            raise ChefUnavailable(f"the model call failed (HTTP {e.status_code})") from e
        except anthropic.APIConnectionError as e:
            logger.warning("model unreachable: %s", type(e).__name__)
            raise ChefUnavailable("the model could not be reached") from e
        if response.stop_reason == "refusal":
            raise ChefUnavailable("the model declined this request")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ChefUnavailable("the model's answer was incomplete")
        return response.parsed_output
