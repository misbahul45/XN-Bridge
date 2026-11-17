import json
import os
import time

import pytest

from scripts import connect_gmail as setup


def client(tmp_path, **changes):
    cfg = {"client_id": "12345-test.apps.googleusercontent.com", "client_secret": "synthetic-fixture-secret", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}
    cfg.update(changes)
    path = tmp_path / "client_secret_test.json"
    path.write_text(json.dumps({"installed": cfg}))
    return path


def test_client_import_is_private_and_does_not_overwrite_existing(tmp_path):
    source = client(tmp_path)
    target = tmp_path / "private/client.json"
    assert setup.install_client(source, target) == "installed"
    assert target.stat().st_mode & 0o777 == 0o600
    assert setup.install_client(source, target) == "installed"
    before = target.read_bytes()
    source = client(tmp_path, client_secret="changed-fixture-secret")
    with pytest.raises(setup.SetupError, match="tidak ditimpa"):
        setup.install_client(source, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("field,value", [("auth_uri", "http://127.0.0.1:1234/steal"), ("token_uri", "https://attacker.example/token"), ("client_id", "not-a-google-client")])
def test_client_rejects_untrusted_endpoints_and_invalid_ids(tmp_path, field, value):
    with pytest.raises(setup.SetupError):
        setup.read_client(client(tmp_path, **{field: value}))


def test_client_rejects_symlinks_and_oversize_content(tmp_path):
    source = client(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(OSError):
        setup.read_client(link)
    source.write_bytes(b" " * 65537)
    with pytest.raises(setup.SetupError, match="terlalu besar"):
        setup.read_client(source)


def test_download_watch_uses_only_one_new_explicit_google_filename(tmp_path):
    path = client(tmp_path)
    since = time.time() - 2
    assert setup.download_candidate(tmp_path, since) == path
    os.utime(path, (since - 30, since - 30))
    assert setup.download_candidate(tmp_path, since) is None
    other = tmp_path / "client_secret_second.json"
    other.write_text("{}")
    os.utime(path, None)
    assert setup.download_candidate(tmp_path, since) is None


def test_missing_client_check_has_no_browser_or_wait_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "CLIENT", tmp_path / "absent.json")
    monkeypatch.setattr(setup.webbrowser, "open", lambda *a: pytest.fail("browser must not open in check mode"))
    assert setup.main(["--check", "--open-console"]) == 2
    assert "Client OAuth Google belum tersedia" in capsys.readouterr().out


def test_unexpected_errors_never_print_secret_payload(tmp_path, monkeypatch, capsys):
    def bad(*args):
        raise ValueError("access_token=fixture-private-value")
    monkeypatch.setattr(setup, "install_client", bad)
    assert setup.main(["--client", str(tmp_path / "any.json")]) == 1
    assert "fixture-private-value" not in capsys.readouterr().err


def test_client_wait_expiry_records_required_instead_of_stale_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PRIVATE", tmp_path / "private")
    monkeypatch.setattr(setup, "CLIENT", tmp_path / "private/client.json")
    assert setup.main(["--wait-for-client", "0"]) == 2
    record = json.loads((tmp_path / "private/gmail-connection-status.json").read_text())
    assert record["status"] == "CLIENT_REQUIRED"
