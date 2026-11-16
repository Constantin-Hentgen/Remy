"""Typed Python client for the Remy HTTP API (needs the ``client`` extra: httpx).

It returns the same pydantic models the service uses, so a bot gets typed objects instead of dicts::

    from remy.client import RemyClient

    with RemyClient("http://remy:8000", api_key="remy_...") as remy:
        candidates = remy.foods("riz blanc cuit")
        logged = remy.log_meal("Riz poulet", items=[{"food_code": "9104", "grams": 200}])
        if logged.possible_duplicate:
            ...  # the client decides: keep both, or remy.delete_meal(logged.meal.id)
        day = remy.day("today")
"""

import datetime
from typing import Any, Literal, Self

import httpx

from remy.foods import Lang
from remy.nutrients import MealComputation, MealItemIn
from remy.schemas import (
    BobImportReport,
    CheckSlot,
    CheckStatus,
    DayOut,
    FoodSearchOut,
    MealIn,
    MealLogged,
    MealOut,
    MealPatch,
    NutrientsIn,
    ProfileIn,
    ProfileOut,
    SlotCheckIn,
    SlotCheckOut,
    WeekOut,
    WorkoutIn,
    WorkoutOut,
)

DateLike = datetime.date | Literal["today", "yesterday"] | str
DEFAULT_TIMEOUT = 10.0


class RemyError(Exception):
    """The service answered with an error status. ``detail`` is its message."""

    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _day(value: DateLike) -> str:
    return value.isoformat() if isinstance(value, datetime.date) else value


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

    def foods(self, q: str, *, lang: Lang | None = None, limit: int = 5) -> FoodSearchOut:
        """Candidate foods for a short description, best first."""
        params: dict[str, Any] = {"q": q, "limit": limit}
        if lang:
            params["lang"] = lang
        return FoodSearchOut.model_validate(self._request("GET", "/v1/foods", params=params))

    def nutrients(self, items: list[MealItemIn | dict[str, Any]], *, lang: Lang | None = None) -> MealComputation:
        """Nutrients of ``[{food_code | food_query, grams}]``; nothing is stored."""
        body = NutrientsIn(items=[MealItemIn.model_validate(i) for i in items], lang=lang)
        return MealComputation.model_validate(self._request("POST", "/v1/nutrients", json=_json(body)))

    # --- profile ----------------------------------------------------------------------------------------------

    def profile(self) -> ProfileOut:
        return ProfileOut.model_validate(self._request("GET", "/v1/me/profile"))

    def put_profile(self, profile: ProfileIn) -> ProfileOut:
        """Replace the profile: fields left out are cleared."""
        return ProfileOut.model_validate(self._request("PUT", "/v1/me/profile", json=_json(profile)))

    def patch_profile(self, **fields: Any) -> ProfileOut:
        """Change only the fields given, e.g. ``patch_profile(weight_kg=71)``. ``None`` clears a field."""
        body = _json(ProfileIn(**fields), include=set(fields))
        return ProfileOut.model_validate(self._request("PATCH", "/v1/me/profile", json=body))

    # --- meals ------------------------------------------------------------------------------------------------

    def log_meal(self, text: str, **fields: Any) -> MealLogged:
        """Log a meal: ``log_meal("Pâtes au thon", at=..., items=[...], source="bob", repeat=False)``."""
        meal = MealIn(text=text, **fields)
        return MealLogged.model_validate(self._request("POST", "/v1/me/meals", json=_json(meal, exclude_none=True)))

    def meals(self, start: DateLike | None = None, end: DateLike | None = None) -> list[MealOut]:
        """Meals between two local dates, inclusive (default: today)."""
        params = {k: _day(v) for k, v in (("from", start), ("to", end)) if v}
        return [MealOut.model_validate(m) for m in self._request("GET", "/v1/me/meals", params=params)]

    def meal(self, meal_id: int) -> MealOut:
        return MealOut.model_validate(self._request("GET", f"/v1/me/meals/{meal_id}"))

    def patch_meal(self, meal_id: int, **fields: Any) -> MealLogged:
        """Correct a meal; sending ``items`` recomputes its nutrients."""
        body = _json(MealPatch(**fields), include=set(fields))
        return MealLogged.model_validate(self._request("PATCH", f"/v1/me/meals/{meal_id}", json=body))

    def delete_meal(self, meal_id: int) -> MealOut:
        """Remove a meal; returns what was removed."""
        return MealOut.model_validate(self._request("DELETE", f"/v1/me/meals/{meal_id}"))

    # --- workouts ---------------------------------------------------------------------------------------------

    def add_workout(self, **fields: Any) -> WorkoutOut:
        """Record a workout. With ``external_id``, sending it again updates the stored one."""
        body = _json(WorkoutIn(**fields), exclude_none=True)
        return WorkoutOut.model_validate(self._request("POST", "/v1/me/workouts", json=body))

    def workouts(self, start: DateLike | None = None, end: DateLike | None = None) -> list[WorkoutOut]:
        params = {k: _day(v) for k, v in (("from", start), ("to", end)) if v}
        return [WorkoutOut.model_validate(w) for w in self._request("GET", "/v1/me/workouts", params=params)]

    def delete_workout(self, workout_id: int) -> WorkoutOut:
        return WorkoutOut.model_validate(self._request("DELETE", f"/v1/me/workouts/{workout_id}"))

    # --- days, weeks, slot checks -----------------------------------------------------------------------------

    def day(self, date: DateLike = "today", *, lang: Lang | None = None) -> DayOut:
        """Totals, needs, balance, macros against their ranges, log issues and anomalies of one day."""
        return DayOut.model_validate(self._request("GET", f"/v1/me/days/{_day(date)}", params=_lang(lang)))

    def week(self, date: DateLike = "yesterday", *, lang: Lang | None = None) -> WeekOut:
        """The 7 days ending on ``date`` (inclusive)."""
        return WeekOut.model_validate(self._request("GET", f"/v1/me/weeks/{_day(date)}", params=_lang(lang)))

    def slot_check(self, date: DateLike, slot: CheckSlot) -> SlotCheckOut:
        """Whether the client already asked about this slot (``status`` is None if not)."""
        return SlotCheckOut.model_validate(self._request("GET", f"/v1/me/slot-checks/{_day(date)}/{slot}"))

    def set_slot_check(self, date: DateLike, slot: CheckSlot, status: CheckStatus) -> SlotCheckOut:
        body = _json(SlotCheckIn(status=status))
        return SlotCheckOut.model_validate(self._request("PUT", f"/v1/me/slot-checks/{_day(date)}/{slot}", json=body))

    # --- import -----------------------------------------------------------------------------------------------

    def import_bob(self, state: dict[str, Any], *, dry_run: bool = False) -> BobImportReport:
        """Import Bob's state file (its parsed JSON): meal log, profile and meal checks. Safe to repeat."""
        params = {"dry_run": "true"} if dry_run else {}
        return BobImportReport.model_validate(self._request("POST", "/v1/me/import/bob", json=state, params=params))


def _lang(lang: Lang | None) -> dict[str, str]:
    return {"lang": lang} if lang else {}


__all__ = ["RemyClient", "RemyError"]
