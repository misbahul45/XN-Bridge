import pytest

from xnbridge.actions import dispatch_action
from xnbridge.errors import PolicyDenied


def action(b, wf, name, payload, domain="research"):
    return dispatch_action(b, domain, name, wf, payload, "DETAIL")


def test_research_mutations_are_blocked_after_completion(bridge):
    wf = bridge.engine.create("research")["id"]
    for stage in ("collect", "verify", "synthesize"):
        bridge.engine.checkpoint(wf, stage, "DONE")
    bridge.engine.transition(wf, "COMPLETED")
    with pytest.raises(PolicyDenied):
        action(bridge, wf, "sources.add", {"sources": [{"title": "Unexpected late mutation"}]})


def test_ats_fetch_cannot_mutate_a_cancelled_workflow(bridge):
    wf = bridge.engine.create("career")["id"]
    bridge.engine.transition(wf, "CANCELLED")
    with pytest.raises(PolicyDenied):
        action(bridge, wf, "opportunities.fetch_ats", {"company_id": "not-executed", "ats": "greenhouse", "slug": "fixture"}, domain="career")


def test_research_verification_cannot_reuse_another_workflows_evidence(bridge):
    wf = bridge.engine.create("research")["id"]
    other = bridge.engine.create("research")["id"]
    out = action(bridge, wf, "sources.add", {"sources": [{"title": "A source paper", "url": "https://example.org/paper"}]})
    source = out["detail"]["source_ids"][0]
    ev = bridge.evidence.register(workflow_id=other, claim="A source paper", origin="tool_output", requested="VERIFIED", source_ref="https://example.org/paper", content="A source paper")
    result = action(bridge, wf, "sources.verify", {"source_id": source, "evidence_id": ev["id"]})
    assert result["verified"] is False


def test_research_brief_rechecks_evidence_expiration(bridge):
    wf = bridge.engine.create("research")["id"]
    out = action(bridge, wf, "sources.add", {"sources": [{"title": "A source paper", "url": "https://example.org/paper"}]})
    source = out["detail"]["source_ids"][0]
    ev = bridge.evidence.register(workflow_id=wf, claim="A source paper", origin="tool_output", requested="VERIFIED", source_ref="https://example.org/paper", content="A source paper")
    assert action(bridge, wf, "sources.verify", {"source_id": source, "evidence_id": ev["id"]})["verified"]
    with bridge.store.tx() as con:
        con.execute("UPDATE evidence SET retrieved_at='2020-01-01T00:00:00.000000Z' WHERE id=?", (ev["id"],))
    result = action(bridge, wf, "brief.finalize", {"title": "A brief", "claims": [{"text": "A supported statement", "source_ids": [source]}]})
    assert result["finalized"] is False
