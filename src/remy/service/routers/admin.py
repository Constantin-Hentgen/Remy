"""Admin routes: users and their API keys. The admin key manages accounts; it cannot read anyone's data."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from remy.schemas import ApiKeyCreated, ApiKeyIn, ApiKeyOut, UserCreated, UserIn, UserOut
from remy.service import security
from remy.service.db import ApiKey, User
from remy.service.deps import Db, require_admin

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, timezone=user.timezone, lang=user.lang, created_at=user.created_at)


def key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        user_id=key.user_id,
        prefix=key.prefix,
        label=key.label,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


def create_user(db: Db, body: UserIn, label: str = "") -> UserCreated:
    """Shared with the CLI."""
    if db.scalar(select(User).where(User.name == body.name)):
        raise ValueError(f"user {body.name!r} already exists")
    user = User(name=body.name, timezone=body.timezone, lang=body.lang, goals={})
    db.add(user)
    key, secret = security.create_api_key(db, user, label)
    db.commit()
    return UserCreated(user=user_out(user), api_key=ApiKeyCreated(**key_out(key).model_dump(), key=secret))


def _user(db: Db, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no user {user_id}")
    return user


@router.post("/users", status_code=status.HTTP_201_CREATED)
def post_user(db: Db, body: UserIn) -> UserCreated:
    """Create a user and their first API key. The key is shown once."""
    try:
        return create_user(db, body)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.get("/users")
def list_users(db: Db) -> list[UserOut]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.get("/users/{user_id}/keys")
def list_keys(db: Db, user_id: int) -> list[ApiKeyOut]:
    return [key_out(k) for k in _user(db, user_id).api_keys]


@router.post("/users/{user_id}/keys", status_code=status.HTTP_201_CREATED)
def post_key(db: Db, user_id: int, body: ApiKeyIn | None = None) -> ApiKeyCreated:
    """Create another API key for a user. The key is shown once."""
    key, secret = security.create_api_key(db, _user(db, user_id), body.label if body else "")
    db.commit()
    return ApiKeyCreated(**key_out(key).model_dump(), key=secret)


@router.post("/keys/{key_id}/revoke")
def revoke_key(db: Db, key_id: int) -> ApiKeyOut:
    """Revoke a key: it stops working at once and is kept for the record."""
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no key {key_id}")
    security.revoke(db, key)
    db.commit()
    return key_out(key)
