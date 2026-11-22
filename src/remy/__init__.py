"""Remy: stateless nutrition for endurance athletes.

The top-level package is the pure computation library. It must stay importable without the web stack (FastAPI), so
that clients such as a chat bot can embed it; the HTTP service lives in :mod:`remy.service` and needs the ``server``
extra.

Modules:

- :mod:`remy.foods`: the Ciqual 2020 table and food search;
- :mod:`remy.nutrients`: nutrients of ``[{food_code | food_query, grams}]``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("remy")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.6.0"

__all__ = ["__version__"]
