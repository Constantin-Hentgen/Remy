"""FastAPI application factory, served with ``uvicorn remy.service.app:create_app --factory``."""

import datetime
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from remy import __version__
from remy.service import logging as service_logging
from remy.service import migrate
from remy.service.db import make_engine
from remy.service.routers import admin, days, foods, imports, meals, profile, slot_checks, workouts
from remy.service.settings import Settings, get_settings

logger = logging.getLogger("remy")

DESCRIPTION = """
Remy is deterministic: **there is no LLM inside, and it never guesses.**

Clients (for instance a chat bot and its LLM) turn free text into structured items `[{food_code | food_query, grams}]`.
Remy returns candidate foods, computes nutrients from the Ciqual 2020 table (ANSES), stores the meal log and flags
what looks wrong.

Authenticate with `Authorization: Bearer <API key>`. Dates and times are in each user's time zone.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` is injectable for tests; production reads the environment."""
    settings = settings or get_settings()
    service_logging.configure(settings.log_level)
    app = FastAPI(title="Remy", version=__version__, summary="Nutrition tracking for endurance athletes.",
                  description=DESCRIPTION)  # fmt: skip

    engine = make_engine(settings.database_url)
    if settings.remy_auto_migrate:
        migrate.upgrade(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False)
    app.state.clock = lambda: datetime.datetime.now(datetime.UTC)  # replaced in tests

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
        """Liveness probe for Docker and Portainer: the process answers and the database is reachable."""
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as e:
            logger.error("health: database unreachable: %s", type(e).__name__)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unreachable") from e
        return {"status": "ok", "version": __version__, "database": "ok"}

    for module in (admin, foods, profile, meals, workouts, days, slot_checks, imports):
        app.include_router(module.router)

    logger.info("Remy %s ready", __version__)
    return app
