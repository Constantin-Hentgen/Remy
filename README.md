# Remy

Named after Remy, the rat chef of *Ratatouille*, who knows exactly what goes into every dish.

**Self-hosted nutrition tracking for endurance athletes.** Remy looks foods up in an open composition table
(Ciqual), computes the nutrients of a meal, keeps a per-user meal log and profile, and computes the daily
**energy balance against training**: intake vs basal metabolism × daily activity + the calories of the day's
workouts. It flags log inconsistencies (a dish logged twice, a missing lunch) and nutrition anomalies (too little
protein, low carbs on a run day).

It is **deterministic: there is no LLM inside.** Clients, such as a chat bot, turn free text into structured items
(`[{food, grams}]`); Remy returns candidate foods, computes, stores and flags. It never guesses.

Use it as a **Python library** (the pure computation core) or as an **HTTP service** (FastAPI, SQLite by default).

> Status: early development. The API is being built; see the [project board](https://github.com/users/Constantin-Hentgen/projects/15).

## Quick start

```sh
cp .env.example .env          # optional: every variable has a default
docker compose up -d
curl http://localhost:18100/health
```

For development:

```sh
uv sync
uv run --frozen python -m pytest -q
uv run --frozen ruff check && uv run --frozen ruff format --check
```

## Documentation

Everything else (configuration, API, data sources, integration with clients) is in the
**[wiki](https://github.com/Constantin-Hentgen/Remy/wiki)**.

## Licence and data

Code: [MIT](LICENSE). Food composition data: **Ciqual 2020 © ANSES**, under the
[Licence Ouverte / Etalab 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/). Open Food Facts data
(planned) is under the [ODbL](https://opendatacommons.org/licenses/odbl/1-0/). Details in [NOTICE](NOTICE).
