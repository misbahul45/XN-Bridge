from __future__ import annotations

import json
import sys
from argparse import Namespace

import pytest

from xnbridge.cli import cmd_catalog
from xnbridge.discovery import ServerProbe, ServerSpec, ToolMeta, host_fingerprint
from xnbridge.errors import ValidationFailed
from xnbridge.host_api import host_probe, list_inventory
from xnbridge.host_catalog import sync_host_catalog


def spec(name="web_search"):
    return ServerSpec(name, "stdio", command=sys.executable)


def row(name="web_search", parameter="string"):
    return {"name": name, "runtimeStatus": "connected", "toolsError": None, "serverInfo": {"name": name, "version": "1"},
            "tools": {"search": {"name": "search", "description": "Search", "inputSchema": {"type": "object", "properties": {"q": {"type": parameter}}}}}}


def test_host_native_contract_is_validated_and_permission_filters_are_respected():
    s = spec()
    p = host_probe(row(), s)
    assert p.status == "OK" and p.tools[0].name == "search"
    assert p.protocol_version is None
    s.permissions = {"disabled_tools": ["search"]}
    assert host_probe(row(), s).tools == []
    bad = row()
    bad["tools"]["search"]["inputSchema"] = "not a schema"
    assert host_probe(bad, spec()).status == "FAILED"


@pytest.mark.parametrize("state,expected", [("authenticationRequired", "AUTH_REQUIRED"), ("starting", "NOT_READY"), ("failed", "FAILED"), ("disabled", "FAILED")])
def test_host_status_does_not_turn_unavailable_tools_into_healthy_ones(state, expected):
    data = row()
    data["runtimeStatus"] = state
    assert host_probe(data, spec()).status == expected


def test_host_pagination_detects_incomplete_catalog():
    calls = []
    def request(method, params, timeout):
        calls.append(params["cursor"])
        return {"data": [row()], "nextCursor": "loop"}
    with pytest.raises(ValidationFailed, match="repeated"):
        list_inventory(request, "thread")
    assert calls == [None, "loop"]


class FakeHost:
    parameter = "string"
    def __init__(self, *, servers):
        self.notifications = [{"name": servers[0], "status": "ready"}]
        self.closed = False
    def start(self, **kw):
        return "thread"
    def inventory(self, name, **kw):
        return [row(name, self.parameter)]
    def close(self):
        self.closed = True


def test_native_refresh_keeps_stable_contracts_cached_and_quarantines_drift(bridge):
    specs = [spec()]
    first = sync_host_catalog(bridge, specs, host_factory=FakeHost)
    assert first["ok"] and first["model_calls"] == 0
    a = bridge.registry.contract("web_search", "search")
    sync_host_catalog(bridge, specs, host_factory=FakeHost)
    assert bridge.registry.contract("web_search", "search")["artifact_id"] == a["artifact_id"]
    class Changed(FakeHost):
        parameter = "integer"
    changed = sync_host_catalog(bridge, specs, host_factory=Changed)
    assert changed["delta"]["changed"] == 1
    assert bridge.registry.resolve("web.search")["selected"] is None
    assert bridge.registry.contract("web_search", "search")["status"] == "CHANGED"


def test_partial_refresh_cannot_bless_an_unscanned_provider_under_changed_host_config(bridge):
    p = host_probe(row(), spec())
    backup = host_probe(row("backup"), spec("backup"))
    bridge.registry.ingest([p, backup], host_fp="before")
    bridge.registry.ingest([p], host_fp="after", active_servers=["web_search", "backup"])
    with bridge.store.read() as con:
        assert con.execute("SELECT status FROM server_health WHERE server='backup'").fetchone()[0] == "STALE"


def test_metadata_refresh_cannot_clear_an_observed_permission_denial(bridge):
    bridge.registry.ingest([ServerProbe("web_search", "stdio", "PERMISSION_DENIED", detail="requires owner context")])
    bridge.registry.ingest([host_probe(row(), spec())])
    out = bridge.registry.resolve("web.search")
    assert out["selected"] is None
    assert out["excluded"][0]["reason"] == "SERVER_PERMISSION_DENIED"


def test_native_refresh_does_not_erase_a_previously_observed_protocol(bridge):
    p = host_probe(row(), spec())
    p.protocol_version = "2025-11-25"
    bridge.registry.ingest([p])
    sync_host_catalog(bridge, [spec()], host_factory=FakeHost)
    contract = bridge.registry.contract("web_search", "search")
    assert contract["protocol_version"] == "2025-11-25" and contract["status"] == "OK"


@pytest.mark.parametrize("seconds,interval", [(301, 1), (-1, 1), (1, 0), (float("nan"), 2)])
def test_watch_limits_reject_unbounded_inputs(bridge, seconds, interval):
    with pytest.raises(ValidationFailed):
        sync_host_catalog(bridge, [spec()], only=["web_search"], watch_seconds=seconds, poll_interval=interval, host_factory=FakeHost)


def test_watch_requires_explicit_server_selection(bridge):
    with pytest.raises(ValidationFailed, match="explicit"):
        sync_host_catalog(bridge, [spec()], watch_seconds=1, host_factory=FakeHost)


def test_changed_catalog_paginates_and_filters_without_loading_other_servers(home, monkeypatch, capsys):
    from xnbridge.app import build
    monkeypatch.setenv("XN_BRIDGE_HOME", str(home))
    b = build(home)
    first = host_probe(row(), spec())
    b.registry.ingest([first, host_probe(row("other"), spec("other"))])
    b.registry.ingest([host_probe(row(parameter="integer"), spec()), host_probe(row("other", "integer"), spec("other"))])
    cmd_catalog(Namespace(action="changed", server="web_search", tool=None, limit=1, offset=0))
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 1 and result["tools"][0]["server"] == "web_search"
    cmd_catalog(Namespace(action="describe", server="web_search", tool="search"))
    detailed = json.loads(capsys.readouterr().out)
    assert detailed["contract"]["inputSchema"]["properties"]["q"]["type"] == "integer"
