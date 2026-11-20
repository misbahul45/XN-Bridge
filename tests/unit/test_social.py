from __future__ import annotations

import pytest

from xnbridge.actions import dispatch_action
from xnbridge.errors import PolicyDenied, ValidationFailed
from xnbridge.routing import Router

TOOLS = {
    "social_auth_connect": "LOCAL_WRITE",
    "social_auth_status": "READ",
    "social_auth_disconnect": "EXTERNAL_WRITE",
    "social_accounts_list": "READ",
    "social_capabilities_get": "READ",
    "social_content_list": "READ",
    "social_content_get": "READ",
    "social_content_create": "LOCAL_WRITE",
    "social_content_publish": "EXTERNAL_WRITE",
    "social_content_update": "EXTERNAL_WRITE",
    "social_content_delete": "EXTERNAL_WRITE",
    "social_engagement_list": "READ",
    "social_engagement_execute": "EXTERNAL_WRITE",
    "social_search": "READ",
    "social_analytics_get": "READ",
    "social_media_upload": "LOCAL_WRITE",
    "social_workflows_execute": "EXTERNAL_WRITE",
    "social_workflows_status": "READ",
    "social_workflows_cancel": "LOCAL_WRITE",
    "social_results_get": "READ",
    "social_approvals_status": "READ",
    "social_system_health": "READ",
}

A1 = "acc_member000000001"
A2 = "acc_page00000000002"
PLAN = "pln_plan000000000001"
HASH = "a" * 64


def test_every_xn_interact_tool_has_the_catalog_risk(bridge):
    for tool, risk in TOOLS.items():
        info = bridge.classifier.classify("xn-interact", tool)
        assert (info.risk, info.source) == (risk, "policy"), tool
    assert bridge.classifier.classify("xn-interact", "social_future_tool").risk == "EXTERNAL_WRITE"


def test_twenty_social_capabilities_map_to_xn_interact(bridge):
    caps = {k: v for k, v in bridge.settings.capabilities["capability"].items() if k.startswith("social.")}
    assert len(caps) == 20
    mapped = sorted(p["tool"] for c in caps.values() for p in c["provider"])
    assert mapped == sorted(TOOLS)
    assert all(p["server"] == "xn-interact" for c in caps.values() for p in c["provider"])
    assert all(c["degraded"] for c in caps.values())


def test_social_domain_records_targets_plan_and_result(bridge):
    wf = bridge.engine.create("social", "publish test")
    assert bridge.domains.spec("social").stage_names == ("connect", "inspect", "collect", "prepare", "act", "verify")
    assert bridge.engine.get(wf["id"])["domain"] == "social"
    dispatch_action(bridge, "social", "targets.set", wf["id"], {"account_ids": [A1, A2], "providers": ["fixture"]}, "SUMMARY")
    with pytest.raises(ValidationFailed):
        dispatch_action(bridge, "social", "plan.record", wf["id"], {"plan_id": PLAN, "plan_hash": HASH, "operation": "social_content_publish", "account_ids": [A1, "acc_unselected000001"]}, "SUMMARY")
    out = dispatch_action(bridge, "social", "plan.record", wf["id"], {"plan_id": PLAN, "plan_hash": HASH, "operation": "social_content_publish", "account_ids": [A1, A2], "interact_approval_id": "apr_interact00000001"}, "SUMMARY")
    assert out["recorded"] is True
    with pytest.raises(ValidationFailed):
        dispatch_action(bridge, "social", "plan.record", wf["id"], {"plan_id": PLAN, "plan_hash": "b" * 64, "operation": "social_content_publish", "account_ids": [A1, A2]}, "SUMMARY")
    res = dispatch_action(bridge, "social", "result.record", wf["id"], {"plan_id": PLAN, "run_id": "run_run0000000000001", "run_state": "partially_succeeded",
                          "targets": [{"account_id": A1, "outcome": "succeeded", "provider_ref": "post-1", "url": "https://fixture.invalid/p/post-1"}, {"account_id": A2, "outcome": "app_approval_required"}]}, "SUMMARY")
    assert res["targets"] == {"succeeded": 1, "app_approval_required": 1}
    with pytest.raises(ValidationFailed):
        dispatch_action(bridge, "social", "result.record", wf["id"], {"plan_id": "pln_unknown000000001", "run_id": "run_run0000000000002", "run_state": "succeeded", "targets": [{"account_id": A1, "outcome": "succeeded"}]}, "SUMMARY")


def test_social_payloads_reject_foreign_ids(bridge):
    wf = bridge.engine.create("social", "ids")
    with pytest.raises(ValidationFailed):
        dispatch_action(bridge, "social", "targets.set", wf["id"], {"account_ids": ["user@example.com"]}, "SUMMARY")
    with pytest.raises(ValidationFailed):
        dispatch_action(bridge, "social", "plan.record", wf["id"], {"plan_id": "x", "plan_hash": HASH, "operation": "p", "account_ids": [A1]}, "SUMMARY")


def test_social_external_write_needs_an_approval_even_with_owner_autonomy(bridge):
    wf = bridge.engine.create("social", "approval")
    bridge.engine.transition(wf["id"], "RUNNING")
    bridge.settings.policy.setdefault("autonomy", {})["unattended_external_writes"] = True
    with pytest.raises(PolicyDenied):
        bridge.executions.begin(workflow_id=wf["id"], capability="social.content.publish", provider="xn-interact:social_content_publish",
                                idempotency_key="k1", target=f"https://xn-interact.invalid/plans/{PLAN}")


@pytest.mark.parametrize("text,intent", [
    ("posting ke linkedin dan threads: rilis fitur baru", "social.publish"),
    ("balas komentar terbaru di instagram", "social.engage"),
    ("lihat analytics tiktok minggu ini", "social.analytics"),
    ("hubungkan akun reddit saya", "social.connect"),
    ("akun facebook mana saja yang terhubung", "social.inspect"),
])
def test_social_requests_route_to_the_social_domain(text, intent):
    d = Router().route(text)
    assert (d.domain, d.intent) == ("social", intent)
    assert d.skill == "xn-social"


@pytest.mark.parametrize("text", ["cari lowongan magang backend di linkedin", "apply internship lewat linkedin", "find internships on linkedin in Jakarta"])
def test_career_requests_never_route_to_social(text):
    assert Router().route(text).domain != "social"


def test_publish_is_flagged_as_external_write():
    assert Router().route("posting ke linkedin: produk baru").requires_human_approval is True


def test_evidence_register_accepts_json_tool_output(tmp_path):
    import asyncio
    import json

    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    from tests.helpers import call, server_params

    async def run():
        async with stdio_client(server_params(tmp_path / "h")) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                _, wf = await call(s, "workflow_create", {"domain": "social", "title": "ev"})
                wid = wf.get("workflow_id") or wf.get("id")
                err, out = await call(s, "evidence_register", {"workflow_id": wid, "claim": "xn-interact run result", "origin": "tool_output",
                                                              "source_ref": "social://results/res_run000000001", "content": json.dumps({"ok": True, "data": {"status": "succeeded"}}), "verification": "VERIFIED"})
                return err, out

    err, out = asyncio.run(run())
    assert not err and out["verification"] == "VERIFIED"
