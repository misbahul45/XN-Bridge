from __future__ import annotations

import pytest

from tests.career_helpers import act, begin_submit, grant_for, ready_submission
from xnbridge.errors import Conflict, LimitExceeded, PolicyDenied

OTHER_JOB = "https://boards.greenhouse.io/northwindlabs/jobs/4002/apply"
OTHER_ORIGIN = "https://jobs.lever.co/northwindlabs/abc/apply"


@pytest.fixture()
def ctx(bridge, monkeypatch):
    return ready_submission(bridge, monkeypatch)


def enable(bridge, **over):
    cfg = bridge.settings.policy.setdefault("autonomy", {})
    cfg.update({"unattended_external_writes": True, **over})


def exec_rows(bridge, wf):
    with bridge.store.read() as con:
        return [dict(r) for r in con.execute("SELECT * FROM executions WHERE workflow_id=?", (wf,))]


def audit_kinds(bridge):
    with bridge.store.read() as con:
        return [r["kind"] for r in con.execute("SELECT kind FROM audit")]


def test_default_policy_still_requires_a_human_approval(bridge, ctx):
    assert bridge.settings.policy["autonomy"]["unattended_external_writes"] is False
    with pytest.raises(PolicyDenied):
        begin_submit(bridge, ctx, None)
    assert exec_rows(bridge, ctx["wf"]) == []


def test_enabled_allows_a_begin_without_approval_and_leaves_an_audit_trail(bridge, ctx):
    enable(bridge)
    out = begin_submit(bridge, ctx, None)
    assert out["risk"] == "EXTERNAL_WRITE" and out["state"] == "STARTED"
    rows = exec_rows(bridge, ctx["wf"])
    assert len(rows) == 1 and rows[0]["approval_id"] is None and rows[0]["payload_digest"] is None and rows[0]["dedupe_key"]
    assert "unattended_external_begin" in audit_kinds(bridge)


def test_duplicate_target_is_blocked_even_with_a_new_idempotency_key(bridge, ctx):
    enable(bridge)
    begin_submit(bridge, ctx, None, key="first")
    with pytest.raises(Conflict):
        begin_submit(bridge, ctx, None, key="second")
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_missing_target_is_rejected(bridge, ctx):
    enable(bridge)
    with pytest.raises(Exception) as e:
        bridge.executions.begin(workflow_id=ctx["wf"], capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="k", approval_id=None)
    assert "target" in str(e.value)


def test_stop_file_halts_unattended_writes_and_removal_resumes_them(bridge, ctx):
    enable(bridge)
    stop = bridge.settings.home / "STOP_EXTERNAL"
    stop.write_text("")
    with pytest.raises(PolicyDenied):
        begin_submit(bridge, ctx, None)
    assert exec_rows(bridge, ctx["wf"]) == []
    stop.unlink()
    assert begin_submit(bridge, ctx, None)["state"] == "STARTED"


def test_daily_cap_blocks_the_next_unattended_action(bridge, ctx):
    enable(bridge, max_external_per_day=1, max_external_per_origin_per_day=10)
    begin_submit(bridge, ctx, None, key="a")
    with pytest.raises(LimitExceeded):
        begin_submit(bridge, ctx, None, key="b", target=OTHER_JOB)
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_origin_cap_limits_one_destination_but_not_another(bridge, ctx):
    enable(bridge, max_external_per_day=10, max_external_per_origin_per_day=1)
    begin_submit(bridge, ctx, None, key="a")
    with pytest.raises(LimitExceeded) as e:
        begin_submit(bridge, ctx, None, key="b", target=OTHER_JOB)
    assert e.value.details["origin"] == "https://boards.greenhouse.io"
    assert begin_submit(bridge, ctx, None, key="c", target=OTHER_ORIGIN)["state"] == "STARTED"


def test_unknown_outcome_is_never_retried_automatically(bridge, ctx):
    enable(bridge)
    first = begin_submit(bridge, ctx, None, key="a")
    out = bridge.executions.finish(execution_id=first["execution_id"], outcome="FAILED", error_class="TRANSPORT", detail={"error": "timeout"})
    assert out["state"] == "OUTCOME_UNKNOWN" and out["recovery"]["action"] == "reconcile"
    with pytest.raises(Exception):
        begin_submit(bridge, ctx, None, key="retry")
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_a_signed_approval_still_works_while_unattended_mode_is_on(bridge, ctx):
    enable(bridge)
    ap = grant_for(bridge, ctx)
    out = begin_submit(bridge, ctx, ap)
    rows = exec_rows(bridge, ctx["wf"])
    assert out["state"] == "STARTED" and rows[0]["payload_digest"] and rows[0]["approval_id"] == ap
    assert bridge.approvals.status(ap)["state"] == "CONSUMED"


def test_unattended_success_flows_through_to_a_submitted_application(bridge, ctx):
    enable(bridge)
    first = begin_submit(bridge, ctx, None)
    ev = bridge.evidence.register(workflow_id=ctx["wf"], claim="Confirmation page: application received", origin="tool_output", requested="VERIFIED", source_ref=ctx["target"], content="Thank you, your application was received", ttl_class="default")
    done = bridge.executions.finish(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[ev["id"]])
    assert done["state"] == "SUCCEEDED"
    assert act(bridge, ctx["wf"], "tracking.update", {"application_id": ctx["app_id"], "status": "SUBMITTED"})["status"] == "SUBMITTED"


def test_unattended_success_without_confirmation_evidence_is_still_unknown(bridge, ctx):
    enable(bridge)
    first = begin_submit(bridge, ctx, None)
    weak = bridge.evidence.register(workflow_id=ctx["wf"], claim="it worked", origin="model_summary", requested="VERIFIED")
    out = bridge.executions.finish(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[weak["id"]])
    assert out["state"] == "OUTCOME_UNKNOWN"
    with pytest.raises(PolicyDenied):
        act(bridge, ctx["wf"], "tracking.update", {"application_id": ctx["app_id"], "status": "SUBMITTED"})


def test_autonomy_never_covers_capabilities_outside_its_allowlist(bridge):
    wf = bridge.engine.create("social", "autonomy scope")
    bridge.engine.transition(wf["id"], "RUNNING")
    enable(bridge)
    with pytest.raises(PolicyDenied):
        bridge.executions.begin(workflow_id=wf["id"], capability="social.content.publish", provider="xn-interact:social_content_publish",
                                idempotency_key="s1", target="https://xn-interact.invalid/plans/pln_scope000000001")
    assert bridge.executions._unattended_enabled("email.send") and bridge.executions._unattended_enabled("browser.form_fill")
    assert not bridge.executions._unattended_enabled("social.engagement.act")

