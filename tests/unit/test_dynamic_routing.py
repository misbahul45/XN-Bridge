from __future__ import annotations

import pytest

from xnbridge.app import build
from xnbridge.errors import ValidationFailed
from xnbridge.routing import CORE_INTENTS, INTENT_BY_KEY, Router, load_intents
from xnbridge.server import build_router


def test_social_intents_are_declarative_not_code():
    core = {i.key for i in CORE_INTENTS}
    assert not any(k.startswith("social.") for k in core)
    assert {"social.connect", "social.publish", "social.engage", "social.analytics", "social.inspect"} <= set(INTENT_BY_KEY)


def test_local_intents_add_and_disable_without_code(home):
    (home / "config").mkdir(parents=True)
    (home / "config" / "intents.toml").write_text('''
[[intent]]
domain = "research"
name = "compare"
stage = "synthesize"
skill = "xn-bridge"
groups = [["\\\\b(bandingkan|compare)\\\\b"], ["\\\\b(paper|metode|methods?)\\\\b"]]
summary = "compare methods across verified sources"

[[intent]]
domain = "social"
name = "analytics"
disabled = true
groups = [["x"]]

[[intent]]
domain = "nonexistent"
name = "thing"
groups = [["\\\\bthing\\\\b"]]
''', encoding="utf-8")
    bridge = build(home)
    intents = load_intents(bridge.settings, bridge.domains)
    keys = {i.key for i in intents}
    assert "research.compare" in keys and "social.analytics" not in keys and "nonexistent.thing" not in keys
    r = build_router(bridge)
    d = r.route("bandingkan metode dari paper yang sudah terverifikasi")
    assert d.intent == "research.compare"


def test_bad_intent_regex_is_rejected(home):
    (home / "config").mkdir(parents=True)
    (home / "config" / "intents.toml").write_text('[[intent]]\ndomain = "research"\nname = "broken"\ngroups = [["(unclosed"]]\n', encoding="utf-8")
    bridge = build(home)
    with pytest.raises(ValidationFailed):
        load_intents(bridge.settings, bridge.domains)


@pytest.mark.parametrize("text,cap", [
    ("baca teks halaman web https://example.com/blog", "web.fetch"),
    ("ekstrak teks dari dokumen pdf ini", "document.extract"),
    ("crawl situs acme.com untuk halaman karier", "web.crawl"),
    ("find the function that handles login in this repo", "code.inspect"),
])
def test_capability_index_routes_requests_without_a_domain(text, cap):
    d = Router().route(text)
    assert d.kind == "capability" and d.capabilities == [cap]


def test_vague_requests_escalate_with_capability_candidates():
    d = Router().route("Buat apa ya enaknya hari ini")
    assert d.kind in ("unrouted", "ambiguous") and d.needs_host_reasoning


def test_a_new_capability_in_config_is_routable_immediately(home):
    (home / "config").mkdir(parents=True)
    (home / "config" / "capabilities.toml").write_text('''
[capability."calendar.read"]
description = "Read calendar events"
keywords = ["calendar", "kalender", "agenda", "jadwal"]
degraded = "Ask the user for the schedule."
[[capability."calendar.read".provider]]
server = "calendar-mcp"
tool = "list_events"
''', encoding="utf-8")
    r = build_router(build(home))
    d = r.route("baca agenda kalender minggu depan")
    assert d.kind == "capability" and d.capabilities == ["calendar.read"]
    assert d.providers["calendar.read"]["status"] in ("DEGRADED", "UNAVAILABLE")
    assert d.next == {"tool": "capability_resolve", "args": {"capability": "calendar.read"}}


def test_decisions_carry_providers_plan_and_next_call(bridge):
    d = build_router(bridge).route("posting ke linkedin dan threads: rilis fitur baru")
    assert d.domain == "social" and d.intent == "social.publish"
    assert [s["stage"] for s in d.plan] == ["prepare", "act", "verify"]
    assert "social.content.publish" in d.plan[1]["providers"]
    assert set(d.providers) == {"social.content.draft", "social.content.publish"}
    assert d.next["tool"] == "workflow_create" and d.next["args"] == {"domain": "social"}
    out = d.as_dict()
    assert out["plan"] and out["providers"] and out["next"]


def test_one_router_spans_every_domain(bridge):
    r = build_router(bridge)
    seen = {r.route(t).domain for t in [
        "Cari magang backend di Surabaya untuk mahasiswa",
        "find recent papers about retrieval augmented generation",
        "lihat analytics tiktok minggu ini",
    ]}
    assert seen == {"career", "research", "social"}


def test_registered_dataset_intents_use_dynamic_provider_resolution(bridge):
    from xnbridge.discovery import ServerProbe, ToolMeta

    names = ["social_extract_start", "social_extract_sources", "social_datasets_query", "social_datasets_export"]
    bridge.registry.ingest([ServerProbe(server="xn-interact", transport="stdio", status="OK", tools=[
        ToolMeta(name, name, {"type": "object"}, None) for name in names
    ])])
    route = build_router(bridge).route("Kumpulkan dataset dari situs yang sudah diotorisasi")
    assert route.intent == "data.collect"
    assert route.providers["data.collect"]["selected"] == "xn-interact:social_extract_start"
    selected = bridge.registry.resolve("data.collect")["selected"]
    assert selected["risk"] == "LOCAL_WRITE"
    assert selected["runtime"]["browser_mode"] == "headless"
    assert selected["runtime"]["requires_extension"] is False
    assert build_router(bridge).route("Ekspor dataset ke CSV").intent == "data.export"
