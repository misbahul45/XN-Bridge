import pytest

from tests.career_helpers import act, new_career, verified_company


@pytest.mark.parametrize("url", ["https://boards.greenhouse.io/unrelated/jobs/123", "https://evilboards.greenhouse.io/northwindlabs/jobs/123"])
def test_known_or_lookalike_ats_host_does_not_prove_board_belongs_to_company(bridge, url):
    wf = new_career(bridge)
    company = verified_company(bridge, wf)
    evidence = bridge.evidence.register(workflow_id=wf, claim="Listing captured", origin="tool_output", requested="VERIFIED", source_ref=url,
                                        content="Python Engineering Intern. Apply now.", provider="web_search:fetchWebContent", ttl_class="listing")
    result = act(bridge, wf, "opportunities.ingest", {"items": [{"company_id": company, "title": "Python Engineering Intern", "url": url, "source": "ats", "evidence_id": evidence["id"]}]})
    assert result["by_status"] == {"LISTED_UNCERTAIN": 1}


def test_captured_company_board_link_verifies_only_its_actual_apply_target(bridge):
    wf = new_career(bridge)
    company = verified_company(bridge, wf)
    url = "https://boards.greenhouse.io/northwindlabs/jobs/123"
    ev = bridge.evidence.register(workflow_id=wf, claim="Listing", origin="tool_output", requested="VERIFIED", source_ref=url,
                                  content="Python Intern apply now", provider="web_search:fetchWebContent", ttl_class="listing")
    payload = {"company_id": company, "title": "Python Intern", "url": url, "source": "ats", "evidence_id": ev["id"]}
    assert act(bridge, wf, "opportunities.ingest", {"items": [payload]})["by_status"] == {"OPEN_VERIFIED": 1}
    payload["apply_url"] = "https://boards.greenhouse.io/unrelated/jobs/123"
    assert act(bridge, wf, "opportunities.ingest", {"items": [payload]})["by_status"] == {"LISTED_UNCERTAIN": 1}


def test_expired_company_link_cannot_keep_fresh_ats_listing_verified(bridge):
    wf = new_career(bridge)
    company = verified_company(bridge, wf)
    url = "https://boards.greenhouse.io/northwindlabs/jobs/123"
    ev = bridge.evidence.register(workflow_id=wf, claim="Listing", origin="tool_output", requested="VERIFIED", source_ref=url,
                                  content="Python Intern apply now", provider="web_search:fetchWebContent", ttl_class="listing")
    payload = {"company_id": company, "title": "Python Intern", "url": url, "source": "ats", "evidence_id": ev["id"]}
    assert act(bridge, wf, "opportunities.ingest", {"items": [payload]})["by_status"] == {"OPEN_VERIFIED": 1}
    with bridge.store.tx() as con:
        con.execute("UPDATE evidence SET retrieved_at='2000-01-01T00:00:00.000000Z' WHERE workflow_id=? AND ttl_class='company'", (wf,))
    assert act(bridge, wf, "opportunity.reverify", {})["changed"] == 1
