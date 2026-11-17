from __future__ import annotations

from tests.career_helpers import act, confirm_all, define_campaign, find_opp, mock_ats, new_career, prepared_workflow, verified_company


def all_boards(bridge, monkeypatch, *, confirm=True, strict=None):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json", "lever": "lever.json", "ashby": "ashby.json"})
    wf = new_career(bridge)
    camp = {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL", "RESEARCH_INTERNSHIP"], "locations": ["Surabaya"], "countries": ["Indonesia"], "scope": "LOCAL"}
    if strict:
        camp["strict"] = strict
    act(bridge, wf, "campaign.define", camp)
    from tests.career_helpers import ingest_cv

    ingest_cv(bridge, wf)
    if confirm:
        confirm_all(bridge, wf)
    cid = verified_company(bridge, wf)
    for name, slug in (("greenhouse", "northwindlabs"), ("lever", "northwindlabs"), ("ashby", "northwind")):
        act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": name, "slug": slug})
    return wf, cid


def by_title(out, needle):
    for r in out["top"]:
        if needle.lower() in r["title"].lower():
            return r
    return None


def test_t13_failed_hard_constraint_is_never_hidden_by_a_high_score(bridge, monkeypatch):
    wf, _ = all_boards(bridge, monkeypatch)
    out = act(bridge, wf, "match.run", {})
    ds = [i for i in out["ineligible"] if "Data Science" in i["title"]][0]
    assert ds["score_hidden_by_failure"] >= 60
    assert any(f["check"] == "work_authorization" and "United States" in f["detail"] for f in ds["failed"])
    assert by_title(out, "Data Science") is None
    assert out["tiers"]["INELIGIBLE"] >= 1
    backend = by_title(out, "Backend Engineering")
    assert backend["tier"] == "ELIGIBLE"


def test_mandatory_skill_gap_and_paid_requirement_fail_hard(bridge, monkeypatch):
    wf, _ = all_boards(bridge, monkeypatch, strict={"paid": True})
    out = act(bridge, wf, "match.run", {})
    research = [i for i in out["ineligible"] if "Research Intern" in i["title"]][0]
    names = {f["check"] for f in research["failed"]}
    assert {"mandatory_skills", "paid"} <= names
    assert any("pytorch" in f["detail"] for f in research["failed"])


def test_unknown_stays_unknown_and_ranks_below_eligible(bridge, monkeypatch):
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json", "ashby": "ashby.json"})
    wf = new_career(bridge)
    act(bridge, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL"})
    from tests.career_helpers import ingest_cv

    ingest_cv(bridge, wf)
    act(bridge, wf, "profile.confirm", {"facts": {"student_status": "enrolled", "availability": {"weeks": 30}}, "quote": "I am a student, free for 30 weeks"})
    cid = verified_company(bridge, wf)
    act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs"})
    act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "ashby", "slug": "northwind"})
    out = act(bridge, wf, "match.run", {})
    backend, pkl = by_title(out, "Backend Engineering"), by_title(out, "PKL Backend")
    assert backend["tier"] == "UNKNOWN_ELIGIBILITY" and "work_authorization" in backend["unknown"]
    assert pkl["tier"] == "ELIGIBLE"
    order = [r["title"] for r in out["top"]]
    assert order.index(pkl["title"]) < order.index(backend["title"])


def test_unconfirmed_profile_never_yields_eligible_for_restricted_listings(bridge, monkeypatch):
    wf, _ = all_boards(bridge, monkeypatch, confirm=False)
    out = act(bridge, wf, "match.run", {})
    assert out["tiers"]["ELIGIBLE"] == 0 or all(r["tier"] != "ELIGIBLE" for r in out["top"] if "Backend Engineering" in r["title"])
    backend = by_title(out, "Backend Engineering")
    assert backend["tier"] == "UNKNOWN_ELIGIBILITY" and {"work_authorization", "student_status"} <= set(backend["unknown"])


def test_soft_score_is_transparent_and_expired_or_unknown_listings_are_skipped(bridge, monkeypatch):
    wf, _ = all_boards(bridge, monkeypatch)
    out = act(bridge, wf, "match.run", {})
    expl = out["top_explanations"][0]
    assert set(expl["soft"]["weights"]) == {"skills", "projects", "experience", "role", "arrangement", "learning"}
    assert 0 < expl["soft"]["coverage"] <= 1
    assert out["skipped_not_matchable"].get("EXPIRED", 0) >= 1
    again = act(bridge, wf, "match.run", {})
    rep = act(bridge, wf, "report.pipeline", {})
    assert sum(rep["match"].values()) == out["matched"] == again["matched"]
