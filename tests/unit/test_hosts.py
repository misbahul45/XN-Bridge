from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from xnbridge.discovery import ServerProbe, ToolMeta, _list_all_tools, host_fingerprint
from xnbridge.hosts import codex_registration, load_codex_servers, load_host_servers


def test_codex_config_preserves_env_and_respects_disabled_servers(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("TEST_HOST_TOKEN", "private-test-token")
    path.write_text('''
[mcp_servers.search]
command = "/usr/bin/search"
args = ["--stdio"]
env_vars = ["TEST_HOST_TOKEN"]
disabled_tools = ["delete"]
[mcp_servers.search.env]
MODE = "read"
[mcp_servers.off]
enabled = false
command = "missing"
[mcp_servers.remote]
url = "https://example.org/mcp"
[mcp_servers.xn-bridge]
command = "python"
''')
    specs = load_host_servers("codex", config=path)
    assert [s.name for s in specs] == ["search", "remote"]
    assert specs[0].env["TEST_HOST_TOKEN"] == "private-test-token"
    assert "private-test-token" not in str(specs[0].public())
    assert specs[1].transport == "http"
    before = host_fingerprint(specs)
    path.write_text(path.read_text().replace('["delete"]', '["delete", "send"]'))
    assert host_fingerprint(load_host_servers("codex", config=path)) != before


def test_partial_discovery_does_not_refresh_old_provider_ttl(bridge):
    from datetime import UTC, datetime, timedelta
    p = ServerProbe("web_search", "stdio", "OK", tools=[ToolMeta("search", "search", {}, None)])
    bridge.registry.ingest([p], host_fp="old")
    old = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with bridge.store.tx() as con:
        con.execute("UPDATE providers SET last_seen_at=?", (old,))
    bridge.registry.ingest([ServerProbe("other", "stdio", "OK")], host_fp="old")
    result = bridge.registry.resolve("web.search")
    assert result["selected"] is None
    assert {"provider": "web_search:search", "reason": "CATALOG_EXPIRED"} in result["excluded"]
    assert bridge.registry.resolve("workflow.persist")["status"] == "AVAILABLE"


def test_host_config_change_invalidates_provider(bridge):
    p = ServerProbe("web_search", "stdio", "OK", tools=[ToolMeta("search", "search", {}, None)])
    bridge.registry.ingest([p], host_fp="before")
    result = bridge.registry.resolve("web.search", current_host_fp="after")
    assert result["selected"] is None
    assert result["excluded"][0]["reason"] == "HOST_CONFIG_CHANGED"


def test_offline_mode_disables_internet_discovery_but_keeps_local_state(bridge):
    bridge.settings.policy["network"]["offline"] = True
    assert bridge.registry.resolve("ats.board_read")["selected"] is None
    assert bridge.registry.resolve("web.search")["selected"] is None
    assert bridge.registry.resolve("workflow.persist")["status"] == "AVAILABLE"


def test_removed_host_provider_cannot_reappear_after_partial_refresh(bridge):
    bridge.registry.ingest([ServerProbe("web_search", "stdio", "OK", tools=[ToolMeta("search", "search", {}, None)])], host_fp="before")
    assert bridge.registry.resolve("web.search")["selected"]
    bridge.registry.ingest([], host_fp="after", active_servers=["other"])
    result = bridge.registry.resolve("web.search", current_host_fp="after")
    assert result["selected"] is None
    assert result["excluded"][0]["reason"] == "SERVER_REMOVED"


def test_public_inventory_removes_separate_secret_arguments_and_url_credentials():
    from xnbridge.discovery import ServerSpec
    spec = ServerSpec("remote", "http", args=["--token", "sensitive-test-token", "--api-key=sensitive-key"], url="https://user:password@example.org:8443/mcp?token=private")
    public = spec.public()
    assert not any(s in str(public) for s in ("sensitive-test-token", "sensitive-key", "password", "token=private"))
    assert public["url"] == "https://example.org:8443/mcp"


def test_output_schema_and_server_version_changes_stay_quarantined(bridge):
    p = ServerProbe("web_search", "stdio", "OK", server_version="1", tools=[ToolMeta("search", "search", {}, {"type": "object"})])
    bridge.registry.ingest([p])
    p.tools[0].output_schema = {"type": "array"}
    assert bridge.registry.ingest([p])["changed"]
    bridge.registry.accept("web_search")
    p.server_version = "2"
    assert bridge.registry.ingest([p])["changed"]
    bridge.registry.ingest([p])
    assert bridge.registry.resolve("web.search")["selected"] is None


def test_pagination_exhaustion_and_repeated_cursor_are_not_success():
    class NeverEnding:
        async def list_tools(self, **kw):
            return SimpleNamespace(tools=[], next_cursor="same")
    with pytest.raises(ValueError, match="repeated"):
        anyio.run(lambda: _list_all_tools(NeverEnding()))
    with pytest.raises(ValueError, match="max_pages"):
        anyio.run(lambda: _list_all_tools(NeverEnding(), max_pages=1))


def test_codex_registration_preserves_configuration_and_is_idempotent():
    import tomllib
    from xnbridge.errors import ValidationFailed
    original = '# keep comments\nmodel = "existing-model"\n[mcp_servers.other]\ncommand = "existing"\n'
    entry = {"command": "/absolute/python", "args": ["-m", "xnbridge.server"], "env": {"XN_BRIDGE_HOME": "/local/data"}}
    merged = codex_registration(original, entry)
    assert merged.startswith(original.rstrip())
    assert tomllib.loads(merged)["mcp_servers"]["other"]["command"] == "existing"
    assert codex_registration(merged, entry) == merged
    with pytest.raises(ValidationFailed, match="refusing"):
        codex_registration(merged, {**entry, "command": "/different/python"})
