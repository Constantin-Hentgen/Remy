"""Open Food Facts products as foods (pure parsing: no network, no database).

Open Food Facts (OFF) is a crowd-sourced database of packaged products, under the ODbL licence. Remy uses it for what
Ciqual cannot give: a specific branded product, found by its barcode. The service fetches and caches it
(``remy.service.openfoodfacts``); this module turns an OFF product into a :class:`~remy.foods.Food`.

A product with no energy value is refused rather than counted as 0 kcal: crowd-sourced data is often incomplete, and
a silent zero would hide it. Other missing nutrients stay unknown (``None``), as in Ciqual.
"""

import re
from collections.abc import Mapping
from typing import Any

from remy.foods import Food, Nutrients

SOURCE = "off"
CODE_PREFIX = "off:"
ATTRIBUTION = "Open Food Facts contributors, ODbL 1.0 (database), DbCL 1.0 (contents). https://world.openfoodfacts.org/"
KJ_PER_KCAL = 4.184
SODIUM_TO_SALT = 2.5
_BARCODE = re.compile(r"^\d{8,14}$")


def is_barcode(text: str) -> bool:
    """EAN-8, UPC-A, EAN-13 and GTIN-14 are 8 to 14 digits."""
    return bool(_BARCODE.match(text))


def food_code(barcode: str) -> str:
    return f"{CODE_PREFIX}{barcode}"


def barcode_of(code: str) -> str | None:
    """The barcode of an ``off:<barcode>`` code, or None for any other code."""
    if code.startswith(CODE_PREFIX) and is_barcode(code[len(CODE_PREFIX) :]):
        return code[len(CODE_PREFIX) :]
    return None


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _text(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def nutrients_of(nutriments: Mapping[str, Any]) -> Nutrients | None:
    """Per-100 g values from OFF's ``nutriments``; None when the product has no energy value."""
    kcal = _number(nutriments.get("energy-kcal_100g"))
    if kcal is None and (kj := _number(nutriments.get("energy_100g"))) is not None:
        kcal = kj / KJ_PER_KCAL
    if kcal is None:
        return None
    salt = _number(nutriments.get("salt_100g"))
    if salt is None and (sodium := _number(nutriments.get("sodium_100g"))) is not None:
        salt = sodium * SODIUM_TO_SALT

    def value(key: str) -> float | None:
        n = _number(nutriments.get(f"{key}_100g"))
        return None if n is None else round(n, 2)

    return Nutrients(
        kcal=round(kcal, 1),
        protein_g=value("proteins"),
        carbs_g=value("carbohydrates"),
        fat_g=value("fat"),
        sugars_g=value("sugars"),
        fiber_g=value("fiber"),
        salt_g=None if salt is None else round(salt, 3),
    )


def parse_product(barcode: str, product: Mapping[str, Any]) -> Food | None:
    """The food for an OFF ``product`` object, or None when it has no usable energy value."""
    nutriments = product.get("nutriments")
    per_100g = nutrients_of(nutriments) if isinstance(nutriments, Mapping) else None
    if per_100g is None:
        return None
    name_fr = (
        _text(product.get("product_name_fr"))
        or _text(product.get("product_name"))
        or _text(product.get("generic_name"))
    )
    name_en = _text(product.get("product_name_en"))
    brand = _text((str(product.get("brands") or "").split(",") or [""])[0])
    return Food(
        code=food_code(barcode),
        name_fr=name_fr or name_en or f"Product {barcode}",
        name_en=name_en,
        brand=brand,
        source=SOURCE,
        per_100g=per_100g,
        attribution=ATTRIBUTION,
    )
