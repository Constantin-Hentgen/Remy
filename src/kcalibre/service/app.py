"""FastAPI application factory, served with ``uvicorn kcalibre.service.app:create_app --factory``."""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from kcalibre import __version__
from kcalibre.service import logging as service_logging
from kcalibre.service.settings import Settings, get_settings

logger = logging.getLogger("kcalibre")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` is injectable for tests; production reads the environment."""
    settings = settings or get_settings()
    service_logging.configure(settings.log_level)
    app = FastAPI(
        title="kcalibre",
        version=__version__,
        summary="Nutrition tracking for endurance athletes: food lookup, meal log, energy balance against training.",
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Path and status only: query strings and bodies can carry health data and must not reach the logs.
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code, ms)
        return response

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        """Liveness probe for Docker and Portainer."""
        return {"status": "ok", "version": __version__}

    logger.info("kcalibre %s ready", __version__)
    return app
