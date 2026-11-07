"""`python -m app.cli turn-off-two-step`, for the server's owner when someone lost their phone and their codes."""

from app import cli
from app.db import Database
from app.db.repositories import two_step, users


def test_the_owner_can_turn_it_off_from_the_command_line(tmp_path, monkeypatch, capsys):
    path = tmp_path / "feedstash.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    db = Database(path)
    db.initialize()
    with db.transaction() as conn:
        user = users.create_local(conn, email="ann@example.com", name=None, password_hash="x", is_admin=False)
        two_step.start(conn, user.id, "secret", now=1)
        two_step.enable(conn, user.id, step=1, now=1)
        version = users.session_version(conn, user.id)
    assert cli.main(["turn-off-two-step", "--email", "ANN@example.com"]) == 0
    assert "Turned off two-step sign-in for ann@example.com" in capsys.readouterr().out
    with db.transaction() as conn:
        assert not two_step.enabled(conn, user.id)
        assert users.session_version(conn, user.id) == version + 1  # signed out everywhere
    assert cli.main(["turn-off-two-step", "--email", "ann@example.com"]) == 1
    assert "isn't on" in capsys.readouterr().err
