from __future__ import annotations

import pytest

from tests.career_helpers import act, define_campaign, new_career, verified_company
from xnbridge.errors import ValidationFailed


def test_campaign_is_dynamic_not_indonesia_only(bridge):
    wf = new_career(bridge)
    out = define_campaign(bridge, wf, roles=["data analyst"], categories=["INTERNSHIP", "GRADUATE"], locations=["Berlin"], countries=["Germany"])
    queries = out["detail"]["queries"]
    assert any("Berlin" in q for q in queries) and not any("magang" in q.lower() for q in queries)
    wf2 = new_career(bridge)
    out2 = define_campaign(bridge, wf2, roles=["backend"], categories=["PKL", "INTERNSHIP"], locations=["Surabaya"])
    assert any("magang" in q.lower() or "praktik kerja" in q.lower() for q in out2["detail"]["queries"])
    wf3 = new_career(bridge)
    out3 = act(bridge, wf3, "campaign.define", {"categories": ["INTERNSHIP_REMOTE", "RESEARCH_INTERNSHIP"], "scope": "REMOTE_WORLDWIDE", "roles": ["machine learning"]})
    assert out3["scope"] == "REMOTE_WORLDWIDE" and any("remote" in q for q in out3["detail"]["queries"])


def test_campaign_queries_are_bounded_and_deduplicated(bridge):
    wf = new_career(bridge)
    out = define_campaign(bridge, wf, roles=["backend", "backend", "ml"], locations=["Surabaya", "surabaya", "Malang"], max_searches=5)
    q = out["detail"]["queries"]
    assert len(q) == 5 and len({x.lower() for x in q}) == 5


def test_campaign_conflicting_constraints_rejected(bridge):
    wf = new_career(bridge)
    with pytest.raises(ValidationFailed):
        define_campaign(bridge, wf, categories=["INTERNSHIP_REMOTE"], remote="EXCLUDED")
    with pytest.raises(ValidationFailed):
        define_campaign(bridge, wf, categories=["INTERNSHIP_PAID"], paid=False)
    with pytest.raises(ValidationFailed):
        define_campaign(bridge, wf, strict={"min_duration_weeks": 20, "max_duration_weeks": 10})
    with pytest.raises(ValidationFailed):
        act(bridge, wf, "campaign.define", {"categories": ["INTERNSHIP"], "scope": "LOCAL"})
    with pytest.raises(ValidationFailed):
        act(bridge, wf, "campaign.define", {"categories": ["DREAM_JOB"], "scope": "WORLDWIDE"})


def test_campaign_separates_hard_constraints_from_preferences(bridge):
    wf = new_career(bridge)
    out = define_campaign(bridge, wf, strict={"paid": True, "must_have_skills": ["python"]}, preferences={"team_size": "small"})
    assert set(out["hard_constraints"]) == {"paid", "must_have_skills"}
    assert out["detail"]["preferences"] == {"team_size": "small"}


def test_identical_campaign_is_not_duplicated(bridge):
    wf = new_career(bridge)
    a = define_campaign(bridge, wf)
    b = define_campaign(bridge, wf)
    assert a["created"] is True and b["created"] is False and a["campaign_id"] == b["campaign_id"]


def add(bridge, wf, *companies):
    return act(bridge, wf, "companies.add", {"companies": list(companies)})


def test_t12_company_deduplication_by_name_and_domain(bridge):
    wf = new_career(bridge)
    out = add(
        bridge, wf,
        {"name": "PT Northwind Labs", "url": "https://www.northwindlabs.example/careers"},
        {"name": "Northwind Labs, Inc.", "url": "https://careers.northwindlabs.example/"},
        {"name": "NORTHWIND LABS", "source": "directory"},
        {"name": "Northwind Labs Academy", "url": "https://academy.example/"},
        {"name": "Contoh Tech", "url": "https://contohtech.co.id/karir"},
    )
    assert out["added"] == 3 and out["merged_duplicates"] == 2
    again = add(bridge, wf, {"name": "Northwind Labs"}, {"name": "Contoh Tech", "url": "https://www.contohtech.co.id"})
    assert again["added"] == 0 and again["merged_duplicates"] == 2
    rep = act(bridge, wf, "report.pipeline", {})
    assert sum(rep["company"].values()) == 3


def test_similar_names_are_not_merged(bridge):
    wf = new_career(bridge)
    out = add(bridge, wf, {"name": "Maju Jaya Teknologi"}, {"name": "Maju Jaya Digital"}, {"name": "Maju Jaya"})
    assert out["added"] == 3 and out["merged_duplicates"] == 0


def test_aggregator_and_bad_urls_do_not_define_identity(bridge):
    wf = new_career(bridge)
    out = add(
        bridge, wf,
        {"name": "Acme Robotics", "url": "https://www.linkedin.com/company/acme-robotics"},
        {"name": "Evil Corp", "url": "http://127.0.0.1:8080/admin"},
        {"name": "Local Corp", "url": "file:///etc/passwd"},
    )
    assert out["added"] == 1 and out["rejected"] == 2
    from xnbridge import entities

    with bridge.store.read() as con:
        acme = entities.listing(con, wf, "company")[0]
    assert acme["data"]["domains"] == [] and acme["status"] == "UNKNOWN"


def test_campaign_company_limit_enforced(bridge):
    wf = new_career(bridge)
    define_campaign(bridge, wf, max_companies=2)
    out = add(bridge, wf, {"name": "Aaa One"}, {"name": "Bbb Two"}, {"name": "Ccc Three"})
    assert out["added"] == 2 and out["rejected"] == 1


def test_domain_verification_requires_fresh_verified_evidence_from_that_domain(bridge):
    wf = new_career(bridge)
    cid = add(bridge, wf, {"name": "Northwind Labs", "url": "https://northwindlabs.example"})["detail"]["added_list"][0]["company_id"]

    def ev(**kw):
        base = dict(workflow_id=wf, claim="official site", origin="tool_output", requested="VERIFIED", source_ref="https://northwindlabs.example/about", content="Northwind Labs", provider="web_search:fetchWebContent", ttl_class="company")
        base.update(kw)
        return bridge.evidence.register(**base)["id"]

    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "northwindlabs.example", "evidence_id": ev(content=None)})
    assert r["verified"] is False and "UNVERIFIED" in r["reason"]
    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "northwindlabs.example", "evidence_id": ev(origin="model_summary")})
    assert r["verified"] is False
    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "northwindlabs.example", "evidence_id": ev(source_ref="https://other.example/page")})
    assert r["verified"] is False and "other.example" in r["reason"]
    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "linkedin.com", "evidence_id": ev(source_ref="https://linkedin.com/company/x")})
    assert r["verified"] is False and "aggregator" in r["reason"]
    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "northwindlabs.example", "evidence_id": ev(ttl_class="company", retrieved_at="2020-01-01T00:00:00.000000Z")})
    assert r["verified"] is False and "stale" in r["reason"]
    r = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": "https://www.northwindlabs.example/x", "evidence_id": ev()})
    assert r["verified"] is True and r["identity"] == "VERIFIED"


def test_same_domain_cannot_verify_two_companies(bridge):
    wf = new_career(bridge)
    first = verified_company(bridge, wf, "Northwind Labs", "https://northwindlabs.example/careers")
    other = add(bridge, wf, {"name": "Totally Different Co"})["detail"]["added_list"][0]["company_id"]
    e = bridge.evidence.register(workflow_id=wf, claim="x", origin="tool_output", requested="VERIFIED", source_ref="https://northwindlabs.example/", content="hello", ttl_class="company")["id"]
    r = act(bridge, wf, "company.verify_domain", {"company_id": other, "domain": "northwindlabs.example", "evidence_id": e})
    assert r["verified"] is False and r["duplicate_of"] == first
