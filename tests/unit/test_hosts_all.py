import json

import pytest

from xnbridge.discovery import host_fingerprint
from xnbridge.errors import ValidationFailed
from xnbridge.hosts import fingerprint_scope, load_host_servers, primary_host, probe_targets


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.delenv("XN_BRIDGE_HOST", raising=False)
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {
        "osm": {"command": "osm-bin", "args": ["--stdio"]},
        "xn-bridge": {"command": "bridge"},
    }}))
    (tmp_path / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": {
        "osm": {"command": "osm-bin", "args": ["--stdio"], "timeout": 9},
        "gmaps": {"command": "gm", "env": {"KEY": "secret-value"}},
        "docs": {"httpUrl": "https://example.org/mcp"},
    }}))
    (tmp_path / ".config" / "opencode" / "opencode.json").write_text(json.dumps({"mcp": {
        "local": {"type": "local", "command": ["lc", "--flag"], "enabled": True},
        "off": {"type": "local", "command": ["x"], "enabled": False},
        "nested": {"figcraft": {"command": "x"}},
    }}))
    return tmp_path


def test_default_scope_combines_every_host_and_hides_secrets(homes):
    assert fingerprint_scope() == "all"
    specs = load_host_servers()
    assert [s.name for s in specs] == ["docs", "gmaps", "local", "osm"]
    assert next(s for s in specs if s.name == "docs").transport == "http"
    local = next(s for s in specs if s.name == "local")
    assert (local.command, local.args) == ("lc", ["--flag"])
    assert "secret-value" not in str([s.public() for s in specs])


def test_fingerprint_is_identical_for_any_host_setting_that_means_all(homes, monkeypatch):
    base = host_fingerprint(load_host_servers())
    for value in ("auto", "all"):
        monkeypatch.setenv("XN_BRIDGE_HOST", value)
        assert host_fingerprint(load_host_servers()) == base
    monkeypatch.setenv("XN_BRIDGE_HOST", "gemini")
    assert host_fingerprint(load_host_servers()) != base


def test_change_in_any_host_configuration_changes_the_fingerprint(homes):
    before = host_fingerprint(load_host_servers())
    path = homes / ".gemini" / "settings.json"
    path.write_text(path.read_text().replace("gm", "gm-evil"))
    assert host_fingerprint(load_host_servers()) != before


def test_identical_definition_in_two_hosts_counts_once_and_probes_once(homes):
    specs = load_host_servers()
    assert [s.name for s in specs].count("osm") == 1
    targets = probe_targets(specs)
    assert [s.name for s in targets] == ["docs", "gmaps", "local", "osm"]


def test_conflicting_definitions_are_all_fingerprinted_but_probed_once(homes):
    base = host_fingerprint(load_host_servers())
    path = homes / ".gemini" / "settings.json"
    data = json.loads(path.read_text())
    data["mcpServers"]["osm"]["args"] = ["--other"]
    path.write_text(json.dumps(data))
    specs = load_host_servers()
    assert [s.name for s in specs].count("osm") == 2
    assert host_fingerprint(specs) != base
    probed = [s for s in probe_targets(specs) if s.name == "osm"]
    assert len(probed) == 1 and probed[0].args == ["--stdio"]


def test_unknown_host_value_is_rejected(homes, monkeypatch):
    monkeypatch.setenv("XN_BRIDGE_HOST", "nonsense")
    with pytest.raises(ValidationFailed):
        fingerprint_scope()
    with pytest.raises(ValidationFailed):
        primary_host()


def test_primary_host_keeps_registration_behavior(homes, monkeypatch):
    assert primary_host() == "claude"
    (homes / ".codex").mkdir()
    (homes / ".codex" / "config.toml").write_text("")
    assert primary_host() == "codex"
    monkeypatch.setenv("XN_BRIDGE_HOST", "all")
    assert primary_host() == "codex"
