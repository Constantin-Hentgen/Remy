"""The remy command line, on a temporary database."""

import pytest
from fastapi.testclient import TestClient

from remy import cli
from remy.service.app import create_app
from remy.service.settings import get_settings


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'remy.db'}")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_user_and_key_lifecycle(database, capsys):
    assert cli.main(["db", "upgrade"]) == 0
    assert cli.main(["user", "create", "alice", "--timezone", "Europe/Lisbon", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    key = out.strip().rsplit(" ", 1)[-1]
    assert "user alice (id 1, Europe/Lisbon, en)" in out and key.startswith("remy_")

    app = create_app()
    client = TestClient(app, headers={"Authorization": f"Bearer {key}"})
    assert client.get("/v1/me/profile").json()["timezone"] == "Europe/Lisbon"

    assert cli.main(["key", "create", "alice", "--label", "bot"]) == 0
    assert cli.main(["key", "list", "alice"]) == 0
    listed = capsys.readouterr().out
    assert "bot" in listed and listed.count("active") == 2 and key not in listed

    assert cli.main(["key", "revoke", "1"]) == 0
    assert client.get("/v1/me/profile").status_code == 401
    assert cli.main(["user", "list"]) == 0
    assert "alice\tEurope/Lisbon\ten" in capsys.readouterr().out
    app.state.engine.dispose()


def test_errors(database, capsys):
    assert cli.main(["user", "create", "alice"]) == 0
    assert cli.main(["user", "create", "alice"]) == 1
    assert cli.main(["user", "create", "bob", "--timezone", "Mars/Olympus"]) == 1
    assert cli.main(["key", "create", "nobody"]) == 1
    assert cli.main(["key", "revoke", "99"]) == 1
    err = capsys.readouterr().err
    assert "already exists" in err and "no user 'nobody'" in err and "no key 99" in err
