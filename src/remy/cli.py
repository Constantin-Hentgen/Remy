"""The ``remy`` command: run the HTTP service (needs the ``server`` extra)."""

import argparse
import sys
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remy", description="Remy: nutrition for endurance athletes.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as e:  # pragma: no cover - depends on the installation
            print(f"remy: serving needs the 'server' extra ({e})", file=sys.stderr)
            return 2
        uvicorn.run("remy.service.app:create_app", factory=True, host=args.host, port=args.port, access_log=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
