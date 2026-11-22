# Remy

Named after Remy, the rat chef of *Ratatouille*, who knows exactly what goes into every dish.

**A stateless nutrition service for endurance athletes.** Tell Remy what you have to cook; it suggests recipes,
with the nutrients of each one computed from an open composition table (Ciqual 2020, ANSES). Nothing is stored:
no account, no meal log, no tracking.

- `POST /v1/suggest`: Claude drafts the recipes from your pantry, meal, servings, target and notes. The numbers are
  never the model's: Remy computes them from Ciqual, and lists any ingredient it could not count.
- `GET /v1/foods` and `POST /v1/nutrients`: Ciqual food search and nutrient computation, without any model.

## Quick start

```sh
cp .env.example .env      # set REMY_API_KEY and ANTHROPIC_API_KEY
docker compose up -d
curl -s -X POST http://localhost:18100/v1/suggest \
  -H "Authorization: Bearer $REMY_API_KEY" -H "Content-Type: application/json" \
  -d '{"pantry": "4 oeufs, riz, épinards, feta", "meal": "dinner", "servings": 2, "notes": "sortie longue demain"}'
```

From a terminal, without the service: `ANTHROPIC_API_KEY=… remy suggest "4 eggs, rice, spinach" --lang en`.
From Python, install the `client` extra:

```python
from remy.client import RemyClient

with RemyClient("http://localhost:18100", api_key=REMY_API_KEY) as remy:
    for recipe in remy.suggest("4 oeufs, riz, épinards", meal="dinner", servings=2).recipes:
        print(recipe.name, recipe.per_serving.kcal)
```

Interactive API docs are served at `/docs`. For development:

```sh
uv sync
uv run --frozen python -m pytest -q
uv run --frozen ruff check && uv run --frozen ruff format --check
```

## Documentation

Configuration, the API and data sources are in the **[wiki](https://github.com/Constantin-Hentgen/Remy/wiki)**.

## Licence and data

Code: [MIT](LICENSE). Food composition data: **Ciqual 2020 © ANSES**, under the
[Licence Ouverte / Etalab 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/). Details in [NOTICE](NOTICE).
Suggestions send each request's pantry, meal, servings, target and notes to Anthropic; nothing else.
