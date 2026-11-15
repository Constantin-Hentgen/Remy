"""The user's profile: what energy needs depend on, plus time zone, language and goals."""

from fastapi import APIRouter, Request

from remy.energy import Profile
from remy.schemas import Goals, ProfileIn, ProfileOut
from remy.service.convert import profile_out
from remy.service.db import User
from remy.service.deps import CurrentUser, Db, local_now

router = APIRouter(prefix="/v1/me", tags=["profile"])

PROFILE_FIELDS = tuple(Profile.model_fields)


def _apply(user: User, body: ProfileIn, fields: set[str], merge_goals: bool = False) -> None:
    for name in PROFILE_FIELDS:
        if name in fields:
            value = getattr(body, name)
            setattr(user, name, value.value if name == "sex" and value else value)
    if "goals" in fields:
        goals = body.goals or Goals()
        if merge_goals and body.goals is not None:
            merged = {**(user.goals or {}), **goals.model_dump(include=goals.model_fields_set)}
            user.goals = {k: v for k, v in merged.items() if v is not None}
        else:
            user.goals = goals.model_dump(exclude_none=True)
    # Time zone and language always have a value: null or omitted keeps the current one.
    if body.timezone:
        user.timezone = body.timezone
    if body.lang:
        user.lang = body.lang


@router.get("/profile")
def get_profile(request: Request, user: CurrentUser) -> ProfileOut:
    return profile_out(user, local_now(request, user).date())


@router.put("/profile")
def put_profile(request: Request, db: Db, user: CurrentUser, body: ProfileIn) -> ProfileOut:
    """Replace the profile: omitted fields are cleared (time zone and language are kept)."""
    _apply(user, body, {*PROFILE_FIELDS, "goals"})
    db.commit()
    return profile_out(user, local_now(request, user).date())


@router.patch("/profile")
def patch_profile(request: Request, db: Db, user: CurrentUser, body: ProfileIn) -> ProfileOut:
    """Change only the fields sent; an explicit null clears a field."""
    _apply(user, body, set(body.model_fields_set), merge_goals=True)
    db.commit()
    return profile_out(user, local_now(request, user).date())
