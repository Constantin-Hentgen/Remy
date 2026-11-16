"""Open Food Facts lookups with a local cache.

What leaves the server: the barcode, in the URL, with a generic User-Agent (no contact details, nothing about the
user). Lookups are rate limited and time out quickly; a failure is never cached, and a stale cache entry is served
when OFF cannot be reached. ``REMY_OFF_ENABLED=false`` turns every outbound request off (cached products still work).
"""

import collections
import datetime
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from remy import __version__, off
from remy.foods import NUTRIENTS, Food, Nutrients
from remy.service.db import OffProduct, utcnow
from remy.service.settings import Settings

logger = logging.getLogger("remy.off")

TIMEOUT_S = 5.0
MAX_PER_MINUTE = 60
"""OFF allows 100 product reads a minute; stay well under."""
NEGATIVE_TTL = datetime.timedelta(days=1)
FIELDS = "code,product_name,product_name_fr,product_name_en,generic_name,brands,nutriments"
USER_AGENT = f"Remy/{__version__} (self-hosted nutrition service; +https://github.com/Constantin-Hentgen/Remy)"


class OffUnavailable(Exception):
    """OFF is disabled, rate limited or unreachable."""


class OpenFoodFacts:
    """Fetches products. ``transport`` is injectable for tests (an ``httpx.MockTransport``)."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.enabled = settings.remy_off_enabled
        self.cache_ttl = datetime.timedelta(days=settings.remy_off_cache_days)
        self._http = httpx.Client(
            base_url=settings.remy_off_base_url.rstrip("/"),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT_S,
            transport=transport,
        )
        self._calls: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def _allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > 60:
                self._calls.popleft()
            if len(self._calls) >= MAX_PER_MINUTE:
                return False
            self._calls.append(now)
            return True

    def fetch(self, barcode: str) -> dict[str, Any] | None:
        """The OFF ``product`` object, or None when OFF does not know the barcode."""
        if not self.enabled:
            raise OffUnavailable("Open Food Facts lookups are disabled (REMY_OFF_ENABLED=false)")
        if not self._allow():
            raise OffUnavailable("too many Open Food Facts lookups, try again in a minute")
        try:
            response = self._http.get(f"/api/v2/product/{barcode}.json", params={"fields": FIELDS})
        except httpx.HTTPError as e:
            logger.warning("OFF unreachable: %s", type(e).__name__)
            raise OffUnavailable("Open Food Facts is unreachable") from e
        if response.status_code == 404:
            return None
        if response.is_error:
            logger.warning("OFF answered %d", response.status_code)
            raise OffUnavailable(f"Open Food Facts answered {response.status_code}")
        try:
            payload = response.json()
        except ValueError as e:
            raise OffUnavailable("Open Food Facts sent an unreadable answer") from e
        product = payload.get("product") if isinstance(payload, dict) and payload.get("status") == 1 else None
        return product if isinstance(product, dict) else None

    def close(self) -> None:
        self._http.close()


def _food(row: OffProduct) -> Food:
    return Food(
        code=off.food_code(row.barcode),
        name_fr=row.name_fr or f"Product {row.barcode}",
        name_en=row.name_en,
        brand=row.brand,
        source=off.SOURCE,
        per_100g=Nutrients(**{k: getattr(row, k) for k in NUTRIENTS}),
        attribution=off.ATTRIBUTION,
    )


def _store(db: Session, barcode: str, food: Food | None, row: OffProduct | None) -> OffProduct:
    row = row or OffProduct(barcode=barcode)
    row.found = food is not None
    row.name_fr = food.name_fr if food else None
    row.name_en = food.name_en if food else None
    row.brand = food.brand if food else None
    for name in NUTRIENTS:
        setattr(row, name, getattr(food.per_100g, name) if food else None)
    row.fetched_at = utcnow()
    db.add(row)
    db.commit()
    return row


def lookup(db: Session, client: OpenFoodFacts, barcode: str) -> Food | None:
    """The product with this barcode: from the cache while fresh, else from OFF.

    None means OFF does not know it (or it has no energy value). Raises :class:`OffUnavailable` when OFF cannot be
    asked and nothing usable is cached.
    """
    row = db.get(OffProduct, barcode)
    age = utcnow() - row.fetched_at if row else None
    if row and age is not None and age < (client.cache_ttl if row.found else NEGATIVE_TTL):
        return _food(row) if row.found else None
    try:
        product = client.fetch(barcode)
    except OffUnavailable:
        if row and row.found:  # stale beats nothing
            return _food(row)
        raise
    food = off.parse_product(barcode, product) if product else None
    _store(db, barcode, food, row)
    return food


def cached_foods(db: Session) -> list[Food]:
    """Every product found so far (what ``GET /v1/foods?source=off`` searches)."""
    return [
        _food(r) for r in db.scalars(select(OffProduct).where(OffProduct.found.is_(True)).order_by(OffProduct.barcode))
    ]


def resolver(db: Session, client: OpenFoodFacts) -> Callable[[str], Food | None]:
    """For :func:`remy.nutrients.compute`: resolves ``off:<barcode>`` codes."""
    from remy.nutrients import FoodUnavailable

    def resolve(code: str) -> Food | None:
        barcode = off.barcode_of(code)
        if barcode is None:
            return None
        try:
            return lookup(db, client, barcode)
        except OffUnavailable as e:
            raise FoodUnavailable(str(e)) from e

    return resolve
