"""FastAPI application factory, served with ``uvicorn remy.service.app:create_app --factory``."""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request, Response

from remy import __version__
from remy.service import logging as service_logging
from remy.service.chef import ClaudeChef
from remy.service.deps import require_key
from remy.service.routers import foods, suggest
from remy.service.settings import Settings, get_settings

logger = logging.getLogger("remy")

DESCRIPTION = """
Remy is stateless: it stores nothing between calls.

- `POST /v1/suggest`: send what you have to cook; Claude drafts recipes and Remy computes their nutrients from the
  Ciqual 2020 table (ANSES). The numbers are never the model's.
- `GET /v1/foods` and `POST /v1/nutrients` look foods up in Ciqual and compute nutrients.

Authenticate with `Authorization: Bearer <REMY_API_KEY>`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` is injectable for tests; production reads the environment."""
    settings = settings or get_settings()
    service_logging.configure(settings.log_level)
    app = FastAPI(title="Remy", version=__version__, summary="Nutrition for endurance athletes.",
                  description=DESCRIPTION)  # fmt: skip
    app.state.settings = settings
    key = settings.anthropic_api_key
    app.state.chef = ClaudeChef(key.get_secret_value(), settings.remy_model) if key else None  # replaced in tests

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

    for module in (foods, suggest):
        app.include_router(module.router, dependencies=[Depends(require_key)])

    if settings.remy_api_key is None:
        logger.warning("REMY_API_KEY is not set: every /v1 call will be refused")
    if key is None:
        logger.warning("ANTHROPIC_API_KEY is not set: POST /v1/suggest will answer 503")
    logger.info("Remy %s ready", __version__)
    return app
