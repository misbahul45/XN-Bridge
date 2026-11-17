from __future__ import annotations

import sys
from pathlib import Path

import anyio
import pytest

from tests.career_helpers import act, new_career
from xnbridge.discovery import ServerProbe, ServerSpec, ToolMeta, discover, host_fingerprint, load_claude_servers, probe_server
from xnbridge.errors import LimitExceeded, NotFound

FAKE = str(Path(__file__).parent.parent / "fixtures" / "fake_server.py")


def spec(name="fakesearch", variant="a"):
    return ServerSpec(name=name, transport="stdio", command=sys.executable, args=[FAKE], env={"FAKE_VARIANT": variant, "FAKE_NAME": name})


def probe(sp):
    return anyio.run(lambda: probe_server(sp, timeout_s=60))


def set_cap(bridge, providers):
    bridge.settings.capabilities["capability"]["web.search"]["provider"] = providers


def prov(server, tool):
    return {"server": server, "tool": tool, "cost": "FREE_LOCAL"}


def failed(name, status="FAILED"):
    return ServerProbe(server=name, transport="stdio", status=status, detail="boom")


def test_real_probe_over_stdio_reports_protocol_schema_and_digest():
    p = probe(spec())
    assert p.status == "OK" and p.protocol_version and p.server_name == "fakesearch"
    t = p.tools[0]
    assert t.name == "search" and t.input_schema["properties"]["q"]["type"] == "string" and len(t.schema_digest) == 64
    assert probe(spec()).tools[0].schema_digest == t.schema_digest


def test_probe_of_a_missing_executable_fails_cleanly_without_crashing_others():
    bad = ServerSpec(name="ghost", transport="stdio", command="/nonexistent/bin/server")
    results = anyio.run(lambda: discover([bad, spec()], timeout_s=30))
    assert [r.status for r in results] == ["FAILED", "OK"]


def test_t04_provider_replacement_when_primary_fails(bridge):
    set_cap(bridge, [prov("fakesearch", "search"), prov("backup", "search")])
    bridge.registry.ingest([probe(spec("fakesearch")), probe(spec("backup"))])
    first = bridge.registry.resolve("web.search")
    assert first["status"] == "AVAILABLE" and first["selected"]["provider"] == "fakesearch:search" and first["fallbacks"][0]["provider"] == "backup:search"
    bridge.registry.ingest([failed("fakesearch")])
    second = bridge.registry.resolve("web.search")
    assert second["selected"]["provider"] == "backup:search"
    assert {"provider": "fakesearch:search", "reason": "SERVER_FAILED"} in second["excluded"]
    forced = bridge.registry.resolve("web.search", exclude=["backup:search"])
    assert forced["status"] == "DEGRADED"


def test_t05_missing_capability_is_an_explicit_degraded_state_never_fabricated(bridge):
    set_cap(bridge, [prov("nobody", "search")])
    out = bridge.registry.resolve("web.search")
    assert out["status"] == "DEGRADED" and out["selected"] is None and out["fallbacks"] == []
    assert "do not invent" in out["degraded_behavior"] and out["excluded"][0]["reason"] == "NOT_DISCOVERED"
    assert bridge.registry.resolve("email.send")["status"] == "DEGRADED"
    with pytest.raises(NotFound):
        bridge.registry.resolve("teleport.anywhere")


def test_schema_change_blocks_provider_until_a_human_accepts(bridge):
    set_cap(bridge, [prov("fakesearch", "search")])
    bridge.registry.ingest([probe(spec(variant="a"))])
    assert bridge.registry.resolve("web.search")["status"] == "AVAILABLE"
    delta = bridge.registry.ingest([probe(spec(variant="schema"))])
    assert delta["changed"] == ["fakesearch:search"]
    out = bridge.registry.resolve("web.search")
    assert out["status"] == "DEGRADED" and out["excluded"][0]["reason"] == "SCHEMA_CHANGED"
    assert bridge.registry.accept("fakesearch", "search") == 1
    assert bridge.registry.resolve("web.search")["status"] == "AVAILABLE"


def test_description_only_change_is_treated_as_a_rug_pull(bridge):
    set_cap(bridge, [prov("fakesearch", "search")])
    bridge.registry.ingest([probe(spec(variant="a"))])
    a, d = probe(spec(variant="a")).tools[0], probe(spec(variant="desc")).tools[0]
    assert a.schema_digest == d.schema_digest and a.desc_digest != d.desc_digest
    assert bridge.registry.ingest([probe(spec(variant="desc"))])["changed"] == ["fakesearch:search"]
    assert bridge.registry.resolve("web.search")["excluded"][0]["reason"] == "SCHEMA_CHANGED"


def test_removed_or_renamed_tools_become_unavailable(bridge):
    set_cap(bridge, [prov("fakesearch", "search")])
    bridge.registry.ingest([probe(spec(variant="a"))])
    delta = bridge.registry.ingest([probe(spec(variant="renamed"))])
    assert delta["gone"] == ["fakesearch:search"] and delta["new"] == ["fakesearch:web_lookup"]
    assert bridge.registry.resolve("web.search")["excluded"][0]["reason"] == "UNAVAILABLE"
    set_cap(bridge, [prov("fakesearch", "web_lookup")])
    assert bridge.registry.resolve("web.search")["status"] == "AVAILABLE"


def test_misleading_tool_descriptions_do_not_influence_selection(bridge):
    set_cap(bridge, [prov("fakesearch", "search")])
    bridge.registry.ingest([probe(spec("evil", "evil")), probe(spec("fakesearch", "a"))])
    out = bridge.registry.resolve("web.search")
    assert out["selected"]["provider"] == "fakesearch:search" and out["fallbacks"] == []
    assert bridge.classifier.classify("evil", "get_status").risk == "EXTERNAL_WRITE"
    assert bridge.classifier.classify("evil", "search").risk == "EXTERNAL_WRITE"


def test_cache_invalidation_signals(bridge):
    sp = [spec()]
    fp1 = host_fingerprint(sp)
    assert bridge.registry.catalog_status()["stale"] is True
    bridge.registry.ingest([probe(sp[0])], host_fp=fp1)
    assert bridge.registry.catalog_status(fp1)["stale"] is False
    fp2 = host_fingerprint(sp + [spec("another")])
    st = bridge.registry.catalog_status(fp2)
    assert st["stale"] is True and st["host_config_changed"] is True
    bridge.settings.policy["limits"]["catalog_ttl_s"] = -1
    assert bridge.registry.catalog_status(fp1)["stale"] is True
    assert "xnbridge discover" in bridge.registry.resolve("web.search", current_host_fp=fp1).get("catalog_note", "")


def test_host_fingerprint_ignores_env_values_and_secrets(monkeypatch, tmp_path):
    cfg = tmp_path / "claude.json"
    cfg.write_text('{"mcpServers": {"a": {"command": "x", "args": ["--token=SECRETVALUE1234567890"], "env": {"API_KEY": "sk-supersecretvalue1234567890"}}}}')
    specs = load_claude_servers(cfg)
    assert "sk-supersecretvalue" not in str(specs[0].public()) and "SECRETVALUE1234567890" not in str(specs[0].public())
    cfg.write_text('{"mcpServers": {"a": {"command": "x", "args": ["--token=SECRETVALUE1234567890"], "env": {"API_KEY": "sk-differentvalue00000000000"}}}}')
    assert host_fingerprint(load_claude_servers(cfg)) == host_fingerprint(specs)


def test_t19_read_failures_recover_with_bounded_retry_then_fallback(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    results = []
    for i, provider in enumerate(["web_search:search", "web_search:search", "web_search:search", "xninetzy:web_search"]):
        ex = bridge.executions.begin(workflow_id=wf["id"], capability="web.search", provider=provider, idempotency_key=f"s{i}")
        assert ex["risk"] == "READ"
        fin = bridge.executions.finish(execution_id=ex["execution_id"], outcome="FAILED", error_class="TRANSPORT")
        results.append(fin["recovery"]["action"])
    assert results[0] == "retry" and "fallback" in results
    counters = bridge.engine.get(wf["id"])["counters"]
    assert counters["provider_switches"] == 1 and counters["tool_calls"] == 4


def test_provider_cooldown_after_repeated_failures_and_recovery_on_success(bridge):
    bridge.settings.policy["risk"].insert(0, {"server": "fakesearch", "tool": "*", "risk": "READ"})
    bridge.settings.policy["risk"].insert(0, {"server": "backup", "tool": "*", "risk": "READ"})
    set_cap(bridge, [prov("fakesearch", "search"), prov("backup", "search")])
    bridge.registry.ingest([probe(spec("fakesearch")), probe(spec("backup"))])
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    bridge.settings.policy["limits"]["max_retries_per_step"] = 10
    for i in range(3):
        ex = bridge.executions.begin(workflow_id=wf["id"], capability="web.search", provider="fakesearch:search", idempotency_key=f"f{i}")
        bridge.executions.finish(execution_id=ex["execution_id"], outcome="FAILED", error_class="TRANSPORT")
    out = bridge.registry.resolve("web.search")
    assert out["selected"]["provider"] == "backup:search" and {"provider": "fakesearch:search", "reason": "COOLDOWN"} in out["excluded"]
    with bridge.store.tx() as con:
        con.execute("UPDATE server_health SET cooldown_until=NULL WHERE server='fakesearch'")
    ex = bridge.executions.begin(workflow_id=wf["id"], capability="web.search", provider="fakesearch:search", idempotency_key="ok")
    bridge.executions.finish(execution_id=ex["execution_id"], outcome="SUCCEEDED")
    assert bridge.registry.resolve("web.search")["selected"]["provider"] == "fakesearch:search"


def test_t24_budgets_are_enforced(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    bridge.settings.policy["limits"]["max_tool_calls"] = 3
    for i in range(3):
        ex = bridge.executions.begin(workflow_id=wf["id"], capability="web.search", provider="web_search:search", idempotency_key=f"t{i}")
        bridge.executions.finish(execution_id=ex["execution_id"], outcome="SUCCEEDED")
    with pytest.raises(LimitExceeded) as e:
        bridge.executions.begin(workflow_id=wf["id"], capability="web.search", provider="web_search:search", idempotency_key="t3")
    assert "tool call budget" in e.value.message
    wf2 = bridge.engine.create("research")
    bridge.engine.checkpoint(wf2["id"], "collect", "RUNNING")
    bridge.settings.policy["limits"].update(max_tool_calls=100, max_browser_ops=2)
    for i in range(2):
        ex = bridge.executions.begin(workflow_id=wf2["id"], capability="browser.inspect", provider="playwright:browser_snapshot", idempotency_key=f"b{i}")
        bridge.executions.finish(execution_id=ex["execution_id"], outcome="SUCCEEDED")
    with pytest.raises(LimitExceeded) as e:
        bridge.executions.begin(workflow_id=wf2["id"], capability="browser.inspect", provider="playwright:browser_snapshot", idempotency_key="b2")
    assert "browser operation budget" in e.value.message
    wf3 = bridge.engine.create("research")
    bridge.engine.checkpoint(wf3["id"], "collect", "RUNNING")
    bridge.settings.policy["limits"].update(max_retries_per_step=1, max_provider_switches=1, max_browser_ops=100)
    seq = ["web_search:search", "web_search:search", "web_search:fetchWebContent", "web_search:fetchWebContent", "web_search:fetchWebContent"]
    with pytest.raises(LimitExceeded):
        for i, p in enumerate(seq):
            ex = bridge.executions.begin(workflow_id=wf3["id"], capability="web.search", provider=p, idempotency_key=f"r{i}")
            bridge.executions.finish(execution_id=ex["execution_id"], outcome="FAILED", error_class="TOOL_ERROR")
