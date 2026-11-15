"""The ``remy`` command: run the service and manage users and API keys (needs the ``server`` extra).

Account management works directly on the database, so it needs no admin key and no running service:
``docker compose exec remy remy user create alice``.
"""

import argparse
import sys
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remy", description="Remy: nutrition tracking for endurance athletes.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    db = sub.add_parser("db", help="database maintenance").add_subparsers(dest="action", required=True)
    db.add_parser("upgrade", help="apply the migrations")

    user = sub.add_parser("user", help="manage users").add_subparsers(dest="action", required=True)
    create = user.add_parser("create", help="create a user and print their first API key")
    create.add_argument("name")
    create.add_argument("--timezone", default="Europe/Paris", help="IANA time zone (default: Europe/Paris)")
    create.add_argument("--lang", default="fr", choices=["fr", "en"])
    create.add_argument("--label", default="", help="label of the first API key")
    user.add_parser("list", help="list users")

    key = sub.add_parser("key", help="manage API keys").add_subparsers(dest="action", required=True)
    key_create = key.add_parser("create", help="create another API key for a user")
    key_create.add_argument("user")
    key_create.add_argument("--label", default="")
    key_list = key.add_parser("list", help="list a user's API keys")
    key_list.add_argument("user")
    key_revoke = key.add_parser("revoke", help="revoke an API key by id")
    key_revoke.add_argument("id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        from pydantic import ValidationError
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from remy.schemas import UserIn
        from remy.service import migrate, security
        from remy.service.db import ApiKey, User, make_engine
        from remy.service.routers.admin import create_user
        from remy.service.settings import get_settings
    except ImportError as e:  # pragma: no cover - depends on the installation
        print(f"remy: the command line needs the 'server' extra ({e})", file=sys.stderr)
        return 2

    if args.command == "serve":
        import uvicorn

        # No access log: it would print query strings, which can carry health data. The app logs requests itself.
        uvicorn.run("remy.service.app:create_app", factory=True, host=args.host, port=args.port, access_log=False)
        return 0

    engine = make_engine(get_settings().database_url)
    migrate.upgrade(engine)
    if args.command == "db":
        print("database is up to date")
        return 0

    def fail(message: str) -> int:
        print(f"remy: {message}", file=sys.stderr)
        return 1

    with Session(engine, expire_on_commit=False) as db:
        if args.command == "user" and args.action == "create":
            try:
                created = create_user(db, UserIn(name=args.name, timezone=args.timezone, lang=args.lang), args.label)
            except (ValueError, ValidationError) as e:
                return fail(str(e))
            print(f"user {created.user.name} (id {created.user.id}, {created.user.timezone}, {created.user.lang})")
            print(f"API key (shown once): {created.api_key.key}")
            return 0
        if args.command == "user" and args.action == "list":
            for u in db.scalars(select(User).order_by(User.id)):
                print(f"{u.id}\t{u.name}\t{u.timezone}\t{u.lang}")
            return 0
        if args.command == "key" and args.action == "revoke":
            row = db.get(ApiKey, args.id)
            if row is None:
                return fail(f"no key {args.id}")
            security.revoke(db, row)
            db.commit()
            print(f"key {row.id} ({row.prefix}…) revoked")
            return 0
        owner = db.scalar(select(User).where(User.name == args.user))
        if owner is None:
            return fail(f"no user {args.user!r}")
        if args.action == "create":
            row, secret = security.create_api_key(db, owner, args.label)
            db.commit()
            print(f"API key {row.id} for {owner.name} (shown once): {secret}")
            return 0
        for k in owner.api_keys:
            state = "revoked" if k.revoked_at else "active"
            print(f"{k.id}\t{k.prefix}…\t{state}\t{k.label}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
