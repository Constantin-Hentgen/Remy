"""Plain-text logging to stdout, one line per event, so ``docker logs`` stays readable."""

import logging

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure(level: str) -> None:
    """Configure the root logger once; uvicorn's own loggers propagate to it."""
    logging.basicConfig(level=level.upper(), format=FORMAT, force=True)
