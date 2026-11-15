"""Remy: nutrition tracking for endurance athletes.

The top-level package is the pure computation library. It must stay importable without the web or database
stack (FastAPI, SQLAlchemy), so that clients such as a chat bot can embed it; the HTTP service lives in
:mod:`remy.service` and needs the ``server`` extra.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("remy")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.1.0"

__all__ = ["__version__"]
