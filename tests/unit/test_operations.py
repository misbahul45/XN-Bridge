from argparse import Namespace
import sqlite3

import pytest

from xnbridge.app import build
from xnbridge.cli import cmd_backup, cmd_restore
from xnbridge.errors import ValidationFailed


def test_restore_rejects_missing_unrelated_and_live_databases(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XN_BRIDGE_HOME", str(home))
    b = build(home)
    wid = b.engine.create("research")["id"]
    unrelated = tmp_path / "unrelated.db"
    sqlite3.connect(unrelated).close()
    for source in (tmp_path / "absent.db", unrelated, b.settings.db_path):
        with pytest.raises(ValidationFailed):
            cmd_restore(Namespace(source=str(source)))
    assert not (tmp_path / "absent.db").exists()
    assert build(home).engine.get(wid)["state"] == "PLANNED"


def test_backup_restore_preserves_snapshot_and_keeps_previous_database(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XN_BRIDGE_HOME", str(home))
    b = build(home)
    first = b.engine.create("research")["id"]
    dest = tmp_path / "backup.db"
    assert cmd_backup(Namespace(out=str(dest))) == 0
    assert dest.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValidationFailed):
        cmd_backup(Namespace(out=str(dest)))
    b.engine.create("research")
    assert cmd_restore(Namespace(source=str(dest))) == 0
    restored = build(home)
    assert restored.store.integrity()["ok"]
    assert [w["id"] for w in restored.engine.list()] == [first]
    assert list(home.glob("bridge.before-restore-*"))


def test_registration_preview_does_not_print_existing_credentials(tmp_path, capsys):
    import json
    from xnbridge.cli import cmd_register
    path = tmp_path / ".mcp.json"
    original = {"mcpServers": {"existing": {"command": "x", "env": {"API_KEY": "sensitive-fixture-value"}}}}
    path.write_text(json.dumps(original))
    assert cmd_register(Namespace(host="claude", file=str(path), write=False)) == 0
    assert "sensitive-fixture-value" not in capsys.readouterr().out
    assert json.loads(path.read_text()) == original


def test_database_restore_does_not_resurrect_pending_approvals(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XN_BRIDGE_HOME", str(home))
    b = build(home)
    wf = b.engine.create("research")["id"]
    approval = b.approvals.prepare(workflow_id=wf, action_kind="email.send", target="https://example.org/send", payload={"draft": "fixture"})
    dest = tmp_path / "snapshot.db"
    cmd_backup(Namespace(out=str(dest)))
    cmd_restore(Namespace(source=str(dest)))
    assert build(home).approvals.status(approval["approval_id"])["state"] == "REVOKED"


def test_corrupt_database_restore_is_rejected_without_touching_live_state(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XN_BRIDGE_HOME", str(home))
    b = build(home)
    wf = b.engine.create("research")["id"]
    corrupt = tmp_path / "bad.db"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(ValidationFailed):
        cmd_restore(Namespace(source=str(corrupt)))
    assert build(home).engine.get(wf)["state"] == "PLANNED"
