"""Plain-text logging to stdout, one line per event, so ``docker logs`` stays readable."""

import logging

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure(level: str) -> None:
    """Configure the root logger once; uvicorn's own loggers propagate to it."""
    logging.basicConfig(level=level.upper(), format=FORMAT, force=True)
    # The HTTP clients log every request at INFO (and the Anthropic SDK can log bodies at DEBUG): what someone has in
    # their kitchen does not belong in the logs.
    for name in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)
