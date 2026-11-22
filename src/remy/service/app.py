"""FastAPI application factory, served with ``uvicorn remy.service.app:create_app --factory``."""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request, Response

from remy import __version__
from remy.service import logging as service_logging
from remy.service.deps import require_key
from remy.service.routers import foods
from remy.service.settings import Settings, get_settings

logger = logging.getLogger("remy")

DESCRIPTION = """
Remy is stateless: it stores nothing between calls.

- `GET /v1/foods` and `POST /v1/nutrients` look foods up in the Ciqual 2020 table (ANSES) and compute nutrients.

Authenticate with `Authorization: Bearer <REMY_API_KEY>`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` is injectable for tests; production reads the environment."""
    settings = settings or get_settings()
    service_logging.configure(settings.log_level)
    app = FastAPI(title="Remy", version=__version__, summary="Nutrition for endurance athletes.",
                  description=DESCRIPTION)  # fmt: skip
    app.state.settings = settings

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Method, route and status only: query strings, bodies and path values can carry personal data.
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "(unmatched)"
        logger.info("%s %s -> %d (%.0f ms)", request.method, path, response.status_code, ms)
        return response

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        """Liveness probe for Docker and Portainer."""
        return {"status": "ok", "version": __version__}

    app.include_router(foods.router, dependencies=[Depends(require_key)])

    if settings.remy_api_key is None:
        logger.warning("REMY_API_KEY is not set: every /v1 call will be refused")
    logger.info("Remy %s ready", __version__)
    return app
