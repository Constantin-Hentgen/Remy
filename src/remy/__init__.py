"""Remy: nutrition tracking for endurance athletes.

The top-level package is the pure computation library. It must stay importable without the web or database
stack (FastAPI, SQLAlchemy), so that clients such as a chat bot can embed it; the HTTP service lives in
:mod:`remy.service` and needs the ``server`` extra.

Modules:

- :mod:`remy.foods`: the Ciqual 2020 table and food search;
- :mod:`remy.nutrients`: nutrients of a meal from ``[{food_code | food_query, grams}]``;
- :mod:`remy.slots`: meal slots by time of day;
- :mod:`remy.energy`: profile, BMR, workouts, daily needs, reference ranges;
- :mod:`remy.checks`: meals, duplicates, log issues and anomalies;
- :mod:`remy.summary`: day and week summaries.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("remy")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.1.0"

__all__ = ["__version__"]
