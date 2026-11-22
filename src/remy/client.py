"""Typed Python client for the Remy HTTP API (needs the ``client`` extra: httpx).

It returns the same pydantic models the service uses, so a bot gets typed objects instead of dicts::

    from remy.client import RemyClient

    with RemyClient("http://remy:8000", api_key="...") as remy:
        candidates = remy.foods("riz blanc cuit")
        meal = remy.nutrients([{"food_code": "9104", "grams": 200}])
"""

from typing import Any, Self

import httpx

from remy.foods import Lang
from remy.nutrients import MealComputation, MealItemIn
from remy.schemas import FoodSearchOut, NutrientsIn

DEFAULT_TIMEOUT = 10.0


class RemyError(Exception):
    """The service answered with an error status. ``detail`` is its message."""

    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _json(model: Any, **kwargs: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", **kwargs)


class RemyClient:
    """A synchronous client. Pass ``http`` to reuse your own :class:`httpx.Client` (tests do, with the app in-process).

    Every method raises :class:`RemyError` on a 4xx/5xx answer.
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http: httpx.Client | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._owns_http = http is None
        self._http = http or httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)
        if http is not None and api_key:
            self._http.headers["Authorization"] = f"Bearer {api_key}"

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RemyError(response.status_code, detail)
        return response.json()

    # --- foods and nutrients ----------------------------------------------------------------------------------

    def foods(self, q: str, *, lang: Lang = "fr", limit: int = 5) -> FoodSearchOut:
        """Candidate Ciqual foods for a short description, best first."""
        params: dict[str, Any] = {"q": q, "limit": limit, "lang": lang}
        return FoodSearchOut.model_validate(self._request("GET", "/v1/foods", params=params))

    def nutrients(self, items: list[MealItemIn | dict[str, Any]], *, lang: Lang = "fr") -> MealComputation:
        """Nutrients of ``[{food_code | food_query, grams}]``."""
        body = NutrientsIn(items=[MealItemIn.model_validate(i) for i in items], lang=lang)
        return MealComputation.model_validate(self._request("POST", "/v1/nutrients", json=_json(body)))
