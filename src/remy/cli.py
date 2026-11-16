"""The ``remy`` command: run the service and manage users and API keys (needs the ``server`` extra).

Account management works directly on the database, so it needs no admin key and no running service:
``docker compose exec remy remy user create alice``.
"""

import argparse
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from remy.service.db import User


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

    imp = sub.add_parser("import", help="import data from another tool").add_subparsers(dest="action", required=True)
    bob = imp.add_parser("bob", help="import the meal log, profile and meal checks of Bob's state file")
    bob.add_argument("file", help="path of Bob's state file (coach_state.json)")
    bob.add_argument("--user", required=True, help="the Remy user receiving the data")
    bob.add_argument("--dry-run", action="store_true", help="report what would be imported, write nothing")
    return parser


def _import_bob(db: "Session", owner: "User", path: str, dry_run: bool) -> int:
    import json

    from remy.service.importing import import_bob

    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        print(f"remy: cannot read {path}: {e}", file=sys.stderr)
        return 1
    if not isinstance(state, dict):
        print(f"remy: {path} is not a Bob state file", file=sys.stderr)
        return 1
    report = import_bob(db, owner, state, dry_run)
    prefix = "dry run, nothing written: " if dry_run else ""
    print(f"{prefix}meals: {report.meals.imported} imported, {report.meals.already_present} already there, "
          f"{report.meals.invalid} unreadable")  # fmt: skip
    print(f"{prefix}meal checks: {report.meal_checks.imported} imported, {report.meal_checks.already_present} "
          f"already there, {report.meal_checks.invalid} unreadable")  # fmt: skip
    print(
        f"{prefix}profile: set {', '.join(report.profile_set) or 'nothing'}"
        + (f"; kept {', '.join(report.profile_kept)}" if report.profile_kept else "")
    )
    for problem in report.problems:
        print(f"  {problem.section} {problem.ref}: {problem.detail}")
    return 0


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
        if args.command == "import":
            return _import_bob(db, owner, args.file, args.dry_run)
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
