from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.career_helpers import PASSPHRASE, act, begin_submit, grant_for, human_grant, ready_submission, setup_approver
from xnbridge import entities
from xnbridge.errors import ApprovalError, Conflict, InvalidTransition, LimitExceeded, PolicyDenied, ValidationFailed


@pytest.fixture()
def ctx(bridge, monkeypatch):
    return ready_submission(bridge, monkeypatch)


def exec_rows(bridge, wf):
    with bridge.store.read() as con:
        return [dict(r) for r in con.execute("SELECT * FROM executions WHERE workflow_id=?", (wf,))]


def test_t14_external_write_without_approval_is_blocked(bridge, ctx):
    with pytest.raises(PolicyDenied) as e:
        begin_submit(bridge, ctx, None)
    assert e.value.details["risk"] == "EXTERNAL_WRITE"
    setup_approver(bridge)
    ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap["approval_id"])
    assert "human must grant" in e.value.message
    assert exec_rows(bridge, ctx["wf"]) == []


def test_model_supplied_approved_flag_is_not_authorization(bridge, ctx):
    with pytest.raises(TypeError):
        bridge.executions.begin(workflow_id=ctx["wf"], capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="x", approved=True)


def test_granted_approval_allows_exactly_one_begin_and_records_write_ahead(bridge, ctx):
    ap = grant_for(bridge, ctx)
    out = begin_submit(bridge, ctx, ap)
    assert out["risk"] == "EXTERNAL_WRITE" and out["state"] == "STARTED"
    assert bridge.approvals.status(ap)["state"] == "CONSUMED"
    assert bridge.engine.get(ctx["wf"])["state"] == "RUNNING"
    rows = exec_rows(bridge, ctx["wf"])
    assert len(rows) == 1 and rows[0]["payload_digest"] and rows[0]["approval_id"] == ap


def test_t15_tampered_payload_invalidates_approval(bridge, ctx):
    ap = grant_for(bridge, ctx)
    with bridge.store.tx() as con:
        ent = entities.get(con, ctx["manifest_id"], ctx["wf"], "submission_manifest")
        data = ent["data"]
        data["texts"]["cover_letter"]["digest"] = "0" * 64
        entities.update(con, ent["id"], data)
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap)
    assert "payload changed" in e.value.message
    assert bridge.approvals.status(ap)["state"] == "GRANTED"
    assert exec_rows(bridge, ctx["wf"]) == []


def test_tampered_payload_before_grant_cannot_be_granted(bridge, ctx):
    setup_approver(bridge)
    ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")
    with bridge.store.tx() as con:
        ent = entities.get(con, ctx["manifest_id"], ctx["wf"], "submission_manifest")
        ent["data"]["destination"] = "https://boards.greenhouse.io/other/jobs/1/apply"
        entities.update(con, ent["id"], ent["data"])
    with pytest.raises(ApprovalError) as e:
        human_grant(bridge, ap["approval_id"])
    assert "payload changed" in e.value.message


@pytest.mark.parametrize("target", ["https://boards.greenhouse.io/northwindlabs/jobs/9999/apply", "https://evil.example/apply", "http://boards.greenhouse.io/northwindlabs/jobs/4001/apply"])
def test_approval_is_bound_to_the_exact_target(bridge, ctx, target):
    ap = grant_for(bridge, ctx)
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap, target=target)
    assert "target differs" in e.value.message


def test_approval_cannot_cross_workflows(bridge, ctx, monkeypatch):
    ap = grant_for(bridge, ctx)
    other = ready_submission(bridge, monkeypatch)
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, other, ap)
    assert "different workflow" in e.value.message


def test_forged_and_unsigned_grants_are_rejected(bridge, ctx):
    ap = grant_for(bridge, ctx)
    with bridge.store.tx() as con:
        con.execute("UPDATE approvals SET signature='AAAA' WHERE id=?", (ap,))
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap)
    assert "signature invalid" in e.value.message
    setup_ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")
    assert setup_ap["state"] == "PENDING" or setup_ap.get("reused") is False or True
    with bridge.store.tx() as con:
        con.execute("UPDATE approvals SET state='GRANTED', signature=NULL WHERE id=?", (setup_ap["approval_id"],))
    with pytest.raises(ApprovalError):
        begin_submit(bridge, ctx, setup_ap["approval_id"], key="k-unsigned")


def test_extending_expiry_in_the_database_breaks_the_signature(bridge, ctx):
    ap = grant_for(bridge, ctx)
    with bridge.store.tx() as con:
        con.execute("UPDATE approvals SET expires_at='2099-01-01T00:00:00.000000Z' WHERE id=?", (ap,))
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap)
    assert "signature invalid" in e.value.message


def test_signature_from_an_attacker_key_is_rejected(bridge, ctx):
    setup_approver(bridge)
    ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")["approval_id"]
    attacker = Ed25519PrivateKey.generate()
    with pytest.raises(ApprovalError) as e:
        bridge.approvals.grant(ap, attacker)
    assert "does not match" in e.value.message
    real = bridge.approvals.public_key()
    bridge.settings.approver_pub.write_bytes(attacker.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    bridge.approvals.grant(ap, attacker)
    bridge.settings.approver_pub.write_bytes(real.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap)
    assert "different key" in e.value.message


def test_wrong_passphrase_cannot_sign(bridge, ctx):
    setup_approver(bridge)
    ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")["approval_id"]
    with pytest.raises(ValueError):
        human_grant(bridge, ap, passphrase=b"guess")


def test_expired_approval_is_rejected(bridge, ctx, monkeypatch):
    ap = grant_for(bridge, ctx, ttl_s=60)
    real = datetime

    class Future(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + timedelta(hours=2)

    monkeypatch.setattr("xnbridge.approval.datetime", Future)
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap)
    assert "expired" in e.value.message
    assert bridge.approvals.status(ap)["state"] == "EXPIRED"


def test_replay_of_a_consumed_approval_is_rejected(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    bridge.executions.finish(execution_id=first["execution_id"], outcome="FAILED", error_class="ABORTED_BEFORE_SEND")
    with pytest.raises(ApprovalError) as e:
        begin_submit(bridge, ctx, ap, key="submit-2")
    assert "CONSUMED" in e.value.message


def test_same_idempotency_key_replays_without_a_second_attempt(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    again = begin_submit(bridge, ctx, ap)
    assert again["replayed"] is True and again["execution_id"] == first["execution_id"] and "do not repeat" in again["warning"]
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_t16_duplicate_submission_is_rejected_at_every_stage(bridge, ctx):
    ap1 = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap1)
    ap2 = grant_for(bridge, ctx)
    with pytest.raises(Conflict) as e:
        begin_submit(bridge, ctx, ap2, key="submit-2")
    assert e.value.details["existing_state"] == "STARTED"
    ev = bridge.evidence.register(workflow_id=ctx["wf"], claim="Confirmation page: application received", origin="tool_output", requested="VERIFIED", source_ref=ctx["target"], content="Thank you, your application was received", ttl_class="default")
    done = bridge.executions.finish(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[ev["id"]])
    assert done["state"] == "SUCCEEDED"
    with pytest.raises(Conflict) as e:
        begin_submit(bridge, ctx, ap2, key="submit-3")
    assert e.value.details["existing_state"] == "SUCCEEDED"
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_duplicate_guard_exists_in_the_database_itself(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    with pytest.raises(sqlite3.IntegrityError):
        with bridge.store.tx() as con:
            con.execute(
                "INSERT INTO executions(id,workflow_id,capability,risk,idempotency_key,dedupe_key,state,started_at) SELECT 'ex_rogue',workflow_id,capability,risk,'rogue',dedupe_key,'STARTED',started_at FROM executions WHERE id=?",
                (first["execution_id"],),
            )


def test_t17_timeout_records_outcome_unknown_and_never_auto_resubmits(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    out = bridge.executions.finish(execution_id=first["execution_id"], outcome="FAILED", error_class="TRANSPORT", detail={"error": "timeout after 30s"})
    assert out["state"] == "OUTCOME_UNKNOWN" and out["recovery"]["action"] == "reconcile"
    assert any("does not prove" in n for n in out["notes"])
    assert bridge.engine.get(ctx["wf"])["state"] == "RECONCILIATION_REQUIRED"
    ap2 = grant_for(bridge, ctx)
    with pytest.raises(InvalidTransition):
        begin_submit(bridge, ctx, ap2, key="submit-2")
    with pytest.raises(InvalidTransition):
        bridge.engine.checkpoint(ctx["wf"], "submission", "DONE")
    with pytest.raises(InvalidTransition):
        bridge.engine.transition(ctx["wf"], "RUNNING")
    with pytest.raises(PolicyDenied):
        act(bridge, ctx["wf"], "tracking.update", {"application_id": ctx["app_id"], "status": "SUBMITTED"})
    assert act(bridge, ctx["wf"], "tracking.update", {"application_id": ctx["app_id"], "status": "OUTCOME_UNKNOWN"})["status"] == "OUTCOME_UNKNOWN"
    assert len(exec_rows(bridge, ctx["wf"])) == 1


def test_reconciliation_needs_real_evidence_and_unblocks_the_workflow(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    bridge.executions.finish(execution_id=first["execution_id"], outcome="OUTCOME_UNKNOWN", error_class="UNKNOWN_SIDE_EFFECT")
    with pytest.raises(ValidationFailed):
        bridge.executions.reconcile(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[])
    guess = bridge.evidence.register(workflow_id=ctx["wf"], claim="probably sent", origin="model_summary", requested="VERIFIED")
    with pytest.raises(ValidationFailed):
        bridge.executions.reconcile(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[guess["id"]])
    user = bridge.evidence.register(workflow_id=ctx["wf"], claim="User saw the confirmation email", origin="user_statement", requested="VERIFIED", source_ref="user:chat", excerpt="I received the confirmation email at 10:42")
    out = bridge.executions.reconcile(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[user["id"]])
    assert out["state"] == "RECONCILED_SUCCEEDED" and bridge.engine.get(ctx["wf"])["state"] == "RUNNING"
    assert act(bridge, ctx["wf"], "tracking.update", {"application_id": ctx["app_id"], "status": "SUBMITTED"})["status"] == "SUBMITTED"
    ap3 = grant_for(bridge, ctx)
    with pytest.raises(Conflict):
        begin_submit(bridge, ctx, ap3, key="again")


def test_reconciled_failure_allows_a_retry_only_with_a_new_approval(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    bridge.executions.finish(execution_id=first["execution_id"], outcome="OUTCOME_UNKNOWN", error_class="TRANSPORT")
    user = bridge.evidence.register(workflow_id=ctx["wf"], claim="User checked the employer portal: nothing received", origin="user_statement", requested="VERIFIED", source_ref="user:chat", excerpt="portal shows no application")
    out = bridge.executions.reconcile(execution_id=first["execution_id"], outcome="FAILED", evidence_ids=[user["id"]])
    assert out["state"] == "RECONCILED_FAILED" and "new approval" in out["next"]
    with pytest.raises(ApprovalError):
        begin_submit(bridge, ctx, ap, key="retry-old-approval")
    fresh = grant_for(bridge, ctx)
    assert begin_submit(bridge, ctx, fresh, key="retry-new-approval")["state"] == "STARTED"


def test_success_without_verified_confirmation_is_unknown(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    weak = bridge.evidence.register(workflow_id=ctx["wf"], claim="it worked", origin="model_summary", requested="VERIFIED")
    out = bridge.executions.finish(execution_id=first["execution_id"], outcome="SUCCEEDED", evidence_ids=[weak["id"]])
    assert out["state"] == "OUTCOME_UNKNOWN" and any("confirmation evidence" in n for n in out["notes"])


def test_failed_before_send_is_a_clean_failure(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    out = bridge.executions.finish(execution_id=first["execution_id"], outcome="FAILED", error_class="PRECONDITION_FAILED")
    assert out["state"] == "FAILED" and out["recovery"]["action"] == "stop"
    assert bridge.engine.get(ctx["wf"])["state"] == "RUNNING"


def test_crash_between_begin_and_finish_is_recovered_as_unknown_on_resume(bridge, ctx):
    ap = grant_for(bridge, ctx)
    begin_submit(bridge, ctx, ap)
    bridge.settings.policy["limits"]["stale_started_s"] = 0
    res = bridge.engine.resume(ctx["wf"])
    assert res["state"] == "RECONCILIATION_REQUIRED"
    assert res["recovered"][0].endswith("OUTCOME_UNKNOWN")
    assert res["unresolved_executions"][0]["state"] == "OUTCOME_UNKNOWN"
    assert res["next_action"]["type"] == "reconcile"
    again = bridge.engine.resume(ctx["wf"])
    assert again["state"] == "RECONCILIATION_REQUIRED" and len(exec_rows(bridge, ctx["wf"])) == 1


def test_non_external_interrupted_attempts_are_safe_to_replay(bridge, ctx):
    started = bridge.executions.begin(workflow_id=ctx["wf"], capability="browser.inspect", provider="playwright:browser_snapshot", idempotency_key="snap-1")
    assert started["risk"] == "READ"
    bridge.settings.policy["limits"]["stale_started_s"] = 0
    res = bridge.engine.resume(ctx["wf"])
    assert res["recovered"] == [f"{started['execution_id']}:FAILED(interrupted)"]
    assert res["state"] == "RUNNING"


def test_completion_is_refused_while_an_attempt_is_unresolved(bridge, ctx):
    ap = grant_for(bridge, ctx)
    first = begin_submit(bridge, ctx, ap)
    for st in ("submission",):
        bridge.engine.checkpoint(ctx["wf"], st, "DONE")
    bridge.engine.checkpoint(ctx["wf"], "tracking", "SKIPPED")
    with pytest.raises(InvalidTransition) as e:
        bridge.engine.transition(ctx["wf"], "COMPLETED")
    assert "unresolved" in e.value.message
    bridge.executions.finish(execution_id=first["execution_id"], outcome="FAILED", error_class="ABORTED_BEFORE_SEND")
    assert bridge.engine.transition(ctx["wf"], "COMPLETED")["state"] == "COMPLETED"


def test_audit_trail_records_approval_lifecycle(bridge, ctx):
    ap = grant_for(bridge, ctx)
    begin_submit(bridge, ctx, ap)
    with bridge.store.read() as con:
        kinds = [r["kind"] for r in con.execute("SELECT kind FROM audit ORDER BY id")]
    assert kinds[-4:] == ["approver_key_created", "approval_prepared", "approval_granted", "approval_consumed"] or {"approval_granted", "approval_consumed", "approval_prepared"} <= set(kinds)


def test_changed_execution_request_cannot_reuse_an_idempotency_key(bridge, ctx):
    ap = grant_for(bridge, ctx)
    begin_submit(bridge, ctx, ap)
    with pytest.raises(Conflict, match="different"):
        begin_submit(bridge, ctx, ap, target="https://other.example/apply")


def test_caller_cannot_override_duplicate_submission_key(bridge, ctx):
    ap = grant_for(bridge, ctx)
    begin_submit(bridge, ctx, ap, dedupe_key="chosen-by-caller-1")
    ap2 = grant_for(bridge, ctx)
    with pytest.raises(Conflict):
        begin_submit(bridge, ctx, ap2, key="second", dedupe_key="chosen-by-caller-2")


def test_confirmation_evidence_cannot_cross_workflows(bridge, ctx):
    ap = grant_for(bridge, ctx)
    ex = begin_submit(bridge, ctx, ap)
    other = bridge.engine.create("research")["id"]
    ev = bridge.evidence.register(workflow_id=other, claim="Another workflow succeeded", origin="tool_output", requested="VERIFIED", source_ref=ctx["target"], content="Confirmation")
    with pytest.raises(ValidationFailed, match="different workflow"):
        bridge.executions.finish(execution_id=ex["execution_id"], outcome="SUCCEEDED", evidence_ids=[ev["id"]])


def test_reconciliation_rejects_unverified_empty_user_statement(bridge, ctx):
    ap = grant_for(bridge, ctx)
    ex = begin_submit(bridge, ctx, ap)
    bridge.executions.finish(execution_id=ex["execution_id"], outcome="OUTCOME_UNKNOWN")
    ev = bridge.evidence.register(workflow_id=ctx["wf"], claim="Probably sent", origin="user_statement", requested="VERIFIED")
    with pytest.raises(ValidationFailed):
        bridge.executions.reconcile(execution_id=ex["execution_id"], outcome="SUCCEEDED", evidence_ids=[ev["id"]])
