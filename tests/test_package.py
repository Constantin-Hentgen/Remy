"""The library must stay embeddable: importing it must not pull in the web or database stack."""

import subprocess
import sys

import remy

HEAVY = ("fastapi", "starlette", "sqlalchemy", "alembic", "uvicorn")


def test_version_is_a_string():
    assert isinstance(remy.__version__, str)
    assert remy.__version__.count(".") == 2


def test_library_import_is_light():
    code = (
        "import sys, remy, remy.schemas, remy.summary; "
        f"print(','.join(m for m in sys.modules if m.split('.')[0] in {HEAVY!r}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == ""
