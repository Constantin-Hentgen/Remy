"""API keys: generated once, stored as a SHA-256 hash.

Keys are 256 bits of randomness, so a fast unsalted hash is enough: there is nothing to brute-force, unlike a
password. The database never holds a usable key.
"""

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from remy.service.db import ApiKey, User, utcnow

KEY_PREFIX = "remy_"
SHOWN_PREFIX_LENGTH = 10


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(db: Session, user: User, label: str = "") -> tuple[ApiKey, str]:
    """A new key for ``user``. Returns the row and the full key, which is never retrievable again."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(user=user, key_hash=hash_key(key), prefix=key[:SHOWN_PREFIX_LENGTH], label=label)
    db.add(row)
    db.flush()
    return row, key


def user_for_key(db: Session, key: str) -> User | None:
    """The owner of a valid, non-revoked key."""
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(key), ApiKey.revoked_at.is_(None)))
    return row.user if row else None


def revoke(db: Session, key: ApiKey) -> None:
    if key.revoked_at is None:
        key.revoked_at = utcnow()


def is_admin_key(candidate: str, admin_key: str | None) -> bool:
    """Constant-time comparison; no admin key configured means no admin access."""
    return bool(admin_key) and hmac.compare_digest(candidate.encode(), admin_key.encode())
