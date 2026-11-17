from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from xnbridge.actions import dispatch_action
from xnbridge.app import Bridge
from xnbridge.domains.career import ats

FIX = Path(__file__).parent / "fixtures"
PASSPHRASE = b"correct horse battery staple"
PUBLIC_RESOLVER = lambda host: ["93.184.216.34"]


def act(bridge: Bridge, wf: str, action: str, payload: dict[str, Any], domain: str = "career", level: str = "DETAIL") -> dict[str, Any]:
    out = dispatch_action(bridge, domain, action, wf, payload, level)
    return {**out.get("detail", {}), **out}


def new_career(bridge: Bridge, title: str = "career") -> str:
    return bridge.engine.create("career", title)["id"]


def ingest_cv(bridge: Bridge, wf: str, name: str = "cv_good.md") -> dict[str, Any]:
    return act(bridge, wf, "profile.ingest", {"path": str(FIX / name)})


CONFIRMED = {
    "full_name": "Rina Kartika",
    "contact": {"email": "rina.kartika@example.com", "phone": "+62 812 3456 7890"},
    "student_status": "enrolled",
    "graduation_year": 2027,
    "availability": {"start": "2027-06-01", "weeks": 26},
    "work_authorization": ["Indonesia"],
    "location": "Surabaya, Indonesia",
    "languages": {"Indonesian": "native", "English": "professional"},
    "work_preference": "any",
}


def confirm_all(bridge: Bridge, wf: str, **override: Any) -> dict[str, Any]:
    facts = {**CONFIRMED, **override}
    return act(bridge, wf, "profile.confirm", {"facts": facts, "quote": "I am Rina Kartika, an enrolled student in Surabaya, available 26 weeks from June 2027."})


def define_campaign(bridge: Bridge, wf: str, **kw: Any) -> dict[str, Any]:
    payload = {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL", "remote": "ALLOWED"}
    payload.update(kw)
    return act(bridge, wf, "campaign.define", payload)


def verified_company(bridge: Bridge, wf: str, name: str = "Northwind Labs", url: str = "https://www.northwindlabs.example/careers") -> str:
    out = act(bridge, wf, "companies.add", {"companies": [{"name": name, "url": url, "source": "search"}]})
    cid = out["detail"]["added_list"][0]["company_id"] if out["detail"]["added_list"] else out["detail"]["merged_list"][0]["company_id"]
    ev = bridge.evidence.register(
        workflow_id=wf, claim=f"{name} official careers page", origin="tool_output", requested="VERIFIED", source_ref=url,
        content=f"{name} careers. We are hiring interns. https://boards.greenhouse.io/northwindlabs https://jobs.lever.co/northwindlabs https://jobs.ashbyhq.com/northwind", provider="web_search:fetchWebContent", ttl_class="company",
    )
    res = act(bridge, wf, "company.verify_domain", {"company_id": cid, "domain": url.split("/")[2], "evidence_id": ev["id"]})
    assert res["verified"] is True, res
    return cid


def mock_ats(monkeypatch, files: dict[str, str]) -> list[str]:
    calls: list[str] = []

    def fake_get(url: str, *, timeout: float = 20.0, max_bytes: int = ats.MAX_BYTES) -> bytes:
        calls.append(url)
        for key, fname in files.items():
            if key in url:
                return (FIX / "ats" / fname).read_bytes()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ats, "http_get", fake_get)
    monkeypatch.setattr("xnbridge.security.default_resolver", PUBLIC_RESOLVER)
    return calls


def human_grant(bridge: Bridge, approval_id: str, passphrase: bytes = PASSPHRASE) -> dict[str, Any]:
    priv = serialization.load_pem_private_key(bridge.settings.approver_key.read_bytes(), password=passphrase)
    return bridge.approvals.grant(approval_id, priv)


def setup_approver(bridge: Bridge) -> str:
    return bridge.approvals.generate_keypair(PASSPHRASE)


def find_opp(bridge: Bridge, wf: str, needle: str) -> dict[str, Any]:
    from xnbridge import entities

    with bridge.store.read() as con:
        for o in entities.listing(con, wf, "opportunity"):
            if needle.lower() in o["data"]["title"].lower():
                return o
    raise AssertionError(f"no opportunity matching {needle}")


def load_json(name: str) -> Any:
    return json.loads((FIX / name).read_text())


def prepared_workflow(bridge: Bridge, monkeypatch, *, confirm: bool = True, fetch_all: bool = False) -> dict[str, Any]:
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json", "lever": "lever.json", "ashby": "ashby.json"})
    wf = new_career(bridge)
    act(bridge, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL"})
    ingest_cv(bridge, wf)
    if confirm:
        confirm_all(bridge, wf)
    cid = verified_company(bridge, wf)
    act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs", "only_matching_campaign": not fetch_all})
    return {"wf": wf, "cid": cid}


def advance_to(bridge: Bridge, wf: str, stage: str) -> None:
    spec = bridge.domains.spec(bridge.engine.get(wf)["domain"])
    for st in spec.stages:
        if st.name == stage:
            bridge.engine.checkpoint(wf, st.name, "RUNNING")
            return
        bridge.engine.checkpoint(wf, st.name, "DONE")


def ready_submission(bridge: Bridge, monkeypatch, *, cv_copy: Path | None = None) -> dict[str, Any]:
    mock_ats(monkeypatch, {"greenhouse": "greenhouse.json"})
    wf = new_career(bridge)
    act(bridge, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL"})
    if cv_copy is not None:
        cv_copy.write_text((FIX / "cv_good.md").read_text())
        act(bridge, wf, "profile.ingest", {"path": str(cv_copy)})
    else:
        ingest_cv(bridge, wf)
    confirm_all(bridge, wf)
    cid = verified_company(bridge, wf)
    act(bridge, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs"})
    opp = find_opp(bridge, wf, "Backend Engineering")
    act(bridge, wf, "match.run", {})
    prep = act(bridge, wf, "application.prepare", {"opportunity_id": opp["id"]})
    app_id = prep["application_id"]
    texts = {name: bridge.artifacts.read_text(ref["artifact_id"]) for name, ref in prep["draft_artifacts"].items()}
    chk = act(bridge, wf, "draft.check", {"application_id": app_id, "texts": texts})
    assert chk["verdict"] == "PASS", chk
    snap = (FIX / "forms" / "snapshot.raw.txt").read_text()
    fields = act(bridge, wf, "form.parse_snapshot", {"text": snap})["fields"]
    plan = act(bridge, wf, "form.plan", {"application_id": app_id, "fields": fields})
    declarations = [{"label": d["label"], "answer": "Yes" if "authorized" in d["label"] else "I agree", "user_confirmed": True, "quote": "yes, I confirm both"} for d in plan["declarations"]]
    target = "https://boards.greenhouse.io/northwindlabs/jobs/4001/apply"
    cv_art = bridge.artifacts.put(wf, "attachment", b"%PDF-1.4 fixture cv", "application/pdf")
    sub = act(bridge, wf, "submission.prepare", {
        "application_id": app_id, "target_url": target, "texts": texts, "attachments": [{"name": "cv.pdf", "artifact_id": cv_art["id"]}],
        "declarations": declarations, "form_plan_digest": plan["plan_digest"],
    })
    advance_to(bridge, wf, "submission")
    return {"wf": wf, "cid": cid, "opp": opp, "app_id": app_id, "texts": texts, "target": target, "manifest_id": sub["manifest_id"], "declarations": declarations, "plan": plan, "fields": fields}


def grant_for(bridge: Bridge, ctx: dict[str, Any], ttl_s: int | None = None) -> str:
    if not bridge.settings.approver_key.exists():
        setup_approver(bridge)
    ap = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}", ttl_s=ttl_s)
    if bridge.engine.get(ctx["wf"])["state"] == "RUNNING":
        bridge.engine.transition(ctx["wf"], "AWAITING_APPROVAL", "approval prepared")
    human_grant(bridge, ap["approval_id"])
    return ap["approval_id"]


def begin_submit(bridge: Bridge, ctx: dict[str, Any], approval_id: str | None, key: str = "submit-1", **kw: Any) -> dict[str, Any]:
    return bridge.executions.begin(
        workflow_id=ctx["wf"], capability="browser.form_fill", provider="playwright:browser_click", idempotency_key=key, target=kw.pop("target", ctx["target"]),
        approval_id=approval_id, **kw,
    )
