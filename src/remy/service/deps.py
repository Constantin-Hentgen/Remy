"""FastAPI dependencies: database session, authentication, the user's clock."""

import datetime
from collections.abc import Iterator
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from remy.foods import Lang
from remy.service import security
from remy.service.db import User

bearer = HTTPBearer(auto_error=False, description="A user API key, or the admin key on /v1/admin routes.")


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


Db = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def current_user(db: Db, credentials: Credentials) -> User:
    if credentials is None:
        raise _unauthorized("missing API key: send 'Authorization: Bearer <key>'")
    user = security.user_for_key(db, credentials.credentials)
    if user is None:
        raise _unauthorized("invalid or revoked API key")
    return user


def require_admin(request: Request, credentials: Credentials) -> None:
    admin_key = request.app.state.settings.remy_admin_key
    if credentials is None:
        raise _unauthorized("missing admin key")
    if not security.is_admin_key(credentials.credentials, admin_key.get_secret_value() if admin_key else None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin key required")


CurrentUser = Annotated[User, Depends(current_user)]


def local_now(request: Request, user: User) -> datetime.datetime:
    """Now in the user's time zone, naive: "today" is always the user's today."""
    now_utc: datetime.datetime = request.app.state.clock()
    return now_utc.astimezone(ZoneInfo(user.timezone)).replace(tzinfo=None)


def to_local(at: datetime.datetime, user: User) -> datetime.datetime:
    """A client datetime as the user's naive local time: converted when it has an offset, taken as local if not."""
    if at.tzinfo is not None:
        at = at.astimezone(ZoneInfo(user.timezone)).replace(tzinfo=None)
    return at.replace(second=0, microsecond=0)


def parse_day(value: str, today: datetime.date) -> datetime.date:
    """A path date: ISO (2026-11-14), or "today" / "yesterday" in the user's time zone."""
    if value == "today":
        return today
    if value == "yesterday":
        return today - datetime.timedelta(days=1)
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(422, f"invalid date: {value!r}") from e


def user_lang(user: User, lang: Lang | None) -> Lang:
    return lang or ("en" if user.lang == "en" else "fr")
