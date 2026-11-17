from __future__ import annotations

import pytest

from tests.career_helpers import FIX, PUBLIC_RESOLVER, act, define_campaign, find_opp, mock_ats, new_career, verified_company
from xnbridge import entities
from xnbridge.domains.career import ats
from xnbridge.domains.career.opportunities import classify
from xnbridge.errors import PolicyDenied, Unavailable, ValidationFailed


def test_parsers_follow_vendor_shapes():
    gh = ats.parse_greenhouse((FIX / "ats/greenhouse.json").read_bytes())
    assert len(gh) == 5 and gh[0]["title"].startswith("Backend Engineering Intern")
    assert "<p>" not in gh[0]["description"] and "Currently enrolled" in gh[0]["description"]
    lv = ats.parse_lever((FIX / "ats/lever.json").read_bytes())
    assert lv[0]["remote"] is True and lv[0]["category"] == "RESEARCH_INTERNSHIP"
    ab = ats.parse_ashby((FIX / "ats/ashby.json").read_bytes())
    assert len(ab) == 1 and ab[0]["category"] in ("PKL", "INTERNSHIP")


def test_eligibility_extraction_keeps_source_snippets():
    gh = ats.parse_greenhouse((FIX / "ats/greenhouse.json").read_bytes())
    el = ats.extract_eligibility(gh[0]["title"] + "\n" + gh[0]["description"])
    assert el["student_required"] is True and el["work_authorization"] == ["Indonesia"]
    assert el["min_duration_weeks"] == 26 and el["paid"] is True
    assert "python" in el["skills_required"] and "docker" in el["skills_preferred"]
    assert "student_required" in el["sources"]
    us = ats.extract_eligibility(gh[2]["description"])
    assert us["work_authorization"] == ["United States"] and us["sponsorship"] is False
    unpaid = ats.extract_eligibility(ats.parse_lever((FIX / "ats/lever.json").read_bytes())[0]["description"])
    assert unpaid["paid"] is False and unpaid["languages"] == ["English"]


def fetch(bridge, wf, cid, ats_name="greenhouse", slug="northwindlabs", **kw):
    return act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": ats_name, "slug": slug, **kw})


def test_fetch_ats_filters_to_campaign_and_classifies_from_evidence(bridge, monkeypatch):
    calls = mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    wf = new_career(bridge)
    define_campaign(bridge, wf, categories=["INTERNSHIP"])
    cid = verified_company(bridge, wf)
    out = fetch(bridge, wf, cid)
    assert calls == ["https://boards-api.greenhouse.io/v1/boards/northwindlabs/jobs?content=true"]
    assert out["listed"] == 5 and out["kept"] == 4 and out["added"] == 4
    assert out["by_status"] == {"OPEN_VERIFIED": 2, "EXPIRED": 1, "LISTED_UNCERTAIN": 1}
    assert find_opp(bridge, wf, "Backend Engineering")["status"] == "OPEN_VERIFIED"
    assert find_opp(bridge, wf, "Frontend Developer")["status"] == "EXPIRED"
    assert not any("Senior Staff" in o["data"]["title"] for o in _opps(bridge, wf))
    assert "raw_ref" not in out and "RAW_REFERENCE" in out["more"]
    raw = act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs"}, level="RAW_REFERENCE")
    assert raw["raw_ref"]["bytes"] > 100 and raw["raw_ref"]["digest"]


def _opps(bridge, wf):
    with bridge.store.read() as con:
        return entities.listing(con, wf, "opportunity")


def test_t18_prompt_injection_in_a_posting_cannot_change_policy_or_state(bridge, monkeypatch):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    wf = new_career(bridge)
    define_campaign(bridge, wf, categories=["INTERNSHIP"])
    cid = verified_company(bridge, wf)
    fetch(bridge, wf, cid)
    bad = find_opp(bridge, wf, "Marketing Intern")
    assert {"override_instructions", "self_approval", "exfiltration"} <= set(bad["data"]["flags"])
    assert bad["status"] == "LISTED_UNCERTAIN" and "human review" in bad["data"]["status_reasons"][0]
    with bridge.store.read() as con:
        assert con.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0
    assert bridge.engine.get(wf)["state"] == "PLANNED"
    good = find_opp(bridge, wf, "Backend Engineering")
    assert good["status"] == "OPEN_VERIFIED"


def test_t12_refetching_the_same_board_does_not_duplicate(bridge, monkeypatch):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    first = fetch(bridge, wf, cid, only_matching_campaign=False)
    second = fetch(bridge, wf, cid, only_matching_campaign=False)
    assert first["added"] == 5 and second["added"] == 0 and second["duplicates_merged"] == 5
    assert len(_opps(bridge, wf)) == 5
    assert all(len(o["data"]["evidence_ids"]) == 2 for o in _opps(bridge, wf))


def test_fetch_requires_verified_company_and_safe_inputs(bridge, monkeypatch):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    wf = new_career(bridge)
    cid = act(bridge, wf, "companies.add", {"companies": [{"name": "Unverified Co", "url": "https://unverified.example"}]})["detail"]["added_list"][0]["company_id"]
    with pytest.raises(PolicyDenied):
        fetch(bridge, wf, cid)
    with pytest.raises(ValidationFailed):
        fetch(bridge, wf, cid, slug="../../etc/passwd")
    with pytest.raises(ValidationFailed):
        fetch(bridge, wf, cid, ats_name="workday")


def test_offline_mode_disables_bridge_side_fetch(bridge, monkeypatch):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    bridge.settings.policy["network"]["offline"] = True
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    with pytest.raises(Unavailable):
        fetch(bridge, wf, cid)


def test_ssrf_guard_applies_to_ats_hosts(bridge, monkeypatch):
    monkeypatch.setattr(ats, "http_get", lambda *a, **k: pytest.fail("must not fetch"))
    monkeypatch.setattr("xnbridge.security.default_resolver", lambda h: ["10.0.0.7"])
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    with pytest.raises(PolicyDenied):
        fetch(bridge, wf, cid)
    bridge.settings.policy["network"]["allowed_ats_hosts"] = []
    monkeypatch.setattr("xnbridge.security.default_resolver", PUBLIC_RESOLVER)
    with pytest.raises(PolicyDenied):
        fetch(bridge, wf, cid)


def test_http_failures_are_unavailable_not_fabricated(bridge, monkeypatch):
    def boom(*a, **k):
        raise Unavailable("ATS endpoint returned HTTP 503", details={"http_status": 503})

    monkeypatch.setattr(ats, "http_get", boom)
    monkeypatch.setattr("xnbridge.security.default_resolver", PUBLIC_RESOLVER)
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    with pytest.raises(Unavailable):
        fetch(bridge, wf, cid)
    assert _opps(bridge, wf) == []


def ingest(bridge, wf, cid, **item):
    base = {"title": "Platform Intern", "company_id": cid, "url": "https://www.northwindlabs.example/careers/platform-intern", "source": "careers_page"}
    base.update(item)
    return act(bridge, wf, "opportunities.ingest", {"items": [base]})


def ev(bridge, wf, **kw):
    base = dict(workflow_id=wf, claim="listing seen", origin="tool_output", requested="VERIFIED", source_ref="https://www.northwindlabs.example/careers/platform-intern", content="Platform Intern apply now", provider="playwright:browser_snapshot", ttl_class="listing")
    base.update(kw)
    return bridge.evidence.register(**base)["id"]


def test_unknown_is_never_promoted_to_open_verified(bridge):
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    assert ingest(bridge, wf, cid)["by_status"] == {"UNKNOWN": 1}
    assert ingest(bridge, wf, cid, url="https://www.northwindlabs.example/careers/other", evidence_id=ev(bridge, wf, content=None))["by_status"] == {"LISTED_UNCERTAIN": 1}
    assert ingest(bridge, wf, cid, url="https://x.example/p", evidence_id=ev(bridge, wf, origin="model_summary"))["by_status"] == {"LISTED_UNCERTAIN": 1}


def test_listing_statuses_from_source_quality(bridge):
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    e = ev(bridge, wf)
    assert ingest(bridge, wf, cid, evidence_id=e)["by_status"] == {"OPEN_VERIFIED": 1}
    assert ingest(bridge, wf, cid, url="https://glints.com/opportunities/1", source="aggregator", evidence_id=e)["by_status"] == {"LISTED_UNCERTAIN": 1}
    assert ingest(bridge, wf, cid, url="https://elsewhere.example/job/9", evidence_id=e)["by_status"] == {"LISTED_UNCERTAIN": 1}
    assert ingest(bridge, wf, cid, url="https://www.northwindlabs.example/careers/old", evidence_id=e, deadline="2020-01-01")["by_status"] == {"EXPIRED": 1}
    assert ingest(bridge, wf, cid, url="https://www.northwindlabs.example/careers/contact", title="General internship inquiry", source="inquiry", evidence_id=e)["by_status"] == {"INQUIRY_ONLY": 1}
    assert ingest(bridge, wf, cid, url="https://www.northwindlabs.example/careers/closed", description="Sorry, this position is no longer accepting applications.", evidence_id=e)["by_status"] == {"EXPIRED": 1}


def test_unverified_company_blocks_open_verified(bridge):
    wf = new_career(bridge)
    cid = act(bridge, wf, "companies.add", {"companies": [{"name": "Unverified Co", "url": "https://unverified.example"}]})["detail"]["added_list"][0]["company_id"]
    e = ev(bridge, wf, source_ref="https://unverified.example/jobs/1")
    out = ingest(bridge, wf, cid, url="https://unverified.example/jobs/1", evidence_id=e)
    assert out["by_status"] == {"LISTED_UNCERTAIN": 1}
    assert "identity" in _opps(bridge, wf)[0]["data"]["status_reasons"][0]


def test_stale_evidence_demotes_open_verified_on_reverify(bridge):
    wf = new_career(bridge)
    cid = verified_company(bridge, wf)
    e = ev(bridge, wf)
    ingest(bridge, wf, cid, evidence_id=e)
    assert _opps(bridge, wf)[0]["status"] == "OPEN_VERIFIED"
    with bridge.store.tx() as con:
        con.execute("UPDATE evidence SET retrieved_at='2020-01-01T00:00:00.000000Z' WHERE id=?", (e,))
    out = act(bridge, wf, "opportunity.reverify", {})
    assert out["changed"] == 1 and out["detail"]["changes"][0]["to"] == "LISTED_UNCERTAIN"
    assert _opps(bridge, wf)[0]["status"] == "LISTED_UNCERTAIN"


def test_classify_is_pure_and_reports_reasons():
    company = {"data": {"identity": "VERIFIED", "domains": [{"domain": "acme.example", "verified": True}]}}
    item = {"source": "careers_page", "title": "Intern", "apply_url": "https://acme.example/apply", "url": "https://acme.example/j", "description": ""}
    evidence = {"verification": "VERIFIED"}
    status, reasons = classify(item, company, evidence, (True, "ok"))
    assert status == "OPEN_VERIFIED" and len(reasons) == 2
    assert classify(item, company, None, None)[0] == "UNKNOWN"
    assert classify({**item, "deadline": "2001-01-01"}, company, evidence, (True, "ok"), today="2026-11-17")[0] == "EXPIRED"
