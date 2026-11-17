from __future__ import annotations

import subprocess
import sys

import anyio
from mcp import Client

from tests.career_helpers import FIX, PASSPHRASE, human_grant
from tests.helpers import call, error_payload, server_params
from xnbridge.app import build


def run(fn):
    return anyio.run(fn)


async def act(c, wf, action, payload, domain="career", level="DETAIL"):
    err, out = await call(c, "domain_action", {"domain": domain, "action": action, "workflow_id": wf, "payload": payload, "level": level})
    assert not err, out
    return {**out.get("detail", {}), **out}


def test_complete_career_workflow_through_mcp_tools_with_restart_and_human_approval(home):
    snap = (FIX / "forms" / "snapshot.raw.txt").read_text()
    state: dict = {}

    async def part1():
        async with Client(server_params(home)) as c:
            err, route = await call(c, "route_intent", {"text": "Cari magang backend di Surabaya, saya punya CV"})
            assert not err and route["domain"] == "career" and route["model_calls"] == 0
            err, wf = await call(c, "workflow_create", {"domain": "career", "title": "e2e", "idempotency_key": "e2e-1"})
            assert not err and wf["next_action"]["stage"] == "candidate-profile" and wf["next_action"]["load_references"] == ["references/profile.md"]
            wid = state["wf"] = wf["workflow_id"]
            again = await call(c, "workflow_create", {"domain": "career", "idempotency_key": "e2e-1"})
            assert again[1]["workflow_id"] == wid
            await act(c, wid, "profile.ingest", {"path": str(FIX / "cv_good.md")})
            await act(c, wid, "profile.confirm", {"facts": {
                "full_name": "Rina Kartika", "contact": {"email": "rina.kartika@example.com", "phone": "+62 812 3456 7890"}, "student_status": "enrolled",
                "graduation_year": 2027, "availability": {"weeks": 26}, "work_authorization": ["Indonesia"], "location": "Surabaya, Indonesia",
                "languages": {"English": "professional", "Indonesian": "native"}}, "quote": "I am an enrolled student in Surabaya, available 26 weeks."})
            err, cp = await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "candidate-profile", "status": "DONE", "data": {"profile": "v2"}})
            assert not err and cp["next_action"]["stage"] == "campaign"
            await act(c, wid, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL"})
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "campaign", "status": "DONE"})
            comp = await act(c, wid, "companies.add", {"companies": [{"name": "PT Northwind Labs", "url": "https://www.northwindlabs.example/careers"}, {"name": "Northwind Labs Inc", "url": "https://northwindlabs.example"}]})
            assert comp["added"] == 1 and comp["merged_duplicates"] == 1
            state["cid"] = comp["added_list"][0]["company_id"]
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "company-discovery", "status": "DONE"})
            err, ev = await call(c, "evidence_register", {"workflow_id": wid, "claim": "Official careers page of Northwind Labs", "origin": "tool_output", "verification": "VERIFIED", "source_ref": "https://www.northwindlabs.example/careers", "content": "Northwind Labs careers. Backend Engineering Intern: apply now.", "ttl_class": "company", "provider": "web_search:fetchWebContent"})
            assert not err and ev["verification"] == "VERIFIED"
            ver = await act(c, wid, "company.verify_domain", {"company_id": state["cid"], "domain": "northwindlabs.example", "evidence_id": ev["evidence_id"]})
            assert ver["verified"] is True
            return wid

    wid = run(part1)

    async def part2():
        async with Client(server_params(home)) as c:
            err, res = await call(c, "workflow_resume", {"workflow_id": wid})
            assert not err and res["last_checkpoint"]["stage"] == "company-discovery" and res["next_action"]["stage"] == "company-verification"
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "company-verification", "status": "DONE"})
            err, ev = await call(c, "evidence_register", {"workflow_id": wid, "claim": "Backend Engineering Intern listing page", "origin": "tool_output", "verification": "VERIFIED", "source_ref": "https://www.northwindlabs.example/careers/backend-intern", "content": "Backend Engineering Intern. Requirements: currently enrolled in a bachelor's degree, Python required, authorized to work in Indonesia, 6 month internship. Apply now.", "ttl_class": "listing", "provider": "playwright:browser_snapshot"})
            ing = await act(c, wid, "opportunities.ingest", {"items": [{
                "title": "Backend Engineering Intern", "company_id": state["cid"], "url": "https://www.northwindlabs.example/careers/backend-intern", "apply_url": "https://www.northwindlabs.example/careers/backend-intern/apply",
                "source": "careers_page", "evidence_id": ev["evidence_id"], "location": "Surabaya, Indonesia",
                "description": "Currently enrolled in a bachelor's degree. Requirements:\nPython is required.\nMust be authorized to work in Indonesia.\n6 month internship."}]})
            assert ing["by_status"] == {"OPEN_VERIFIED": 1}
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "opportunity-verification", "status": "DONE"})
            m = await act(c, wid, "match.run", {})
            top = m["top"][0]
            assert top["tier"] == "ELIGIBLE"
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "matching", "status": "DONE"})
            prep = await act(c, wid, "application.prepare", {"opportunity_id": top["opportunity_id"]})
            aid = prep["application_id"]
            texts = {}
            for name, ref in prep["draft_artifacts"].items():
                texts[name] = (build(home).artifacts.read_text(ref["artifact_id"]))
            chk = await act(c, wid, "draft.check", {"application_id": aid, "texts": texts})
            assert chk["verdict"] == "PASS"
            form = await act(c, wid, "form.parse_snapshot", {"text": snap})
            plan = await act(c, wid, "form.plan", {"application_id": aid, "fields": form["fields"]})
            decl = [{"label": d["label"], "answer": "Yes" if "authorized" in d["label"] else "I agree", "user_confirmed": True, "quote": "yes, I confirm"} for d in plan["declarations"]]
            art = build(home).artifacts.put(wid, "attachment", b"%PDF-1.4 e2e cv", "application/pdf")
            target = "https://www.northwindlabs.example/careers/backend-intern/apply"
            sub = await act(c, wid, "submission.prepare", {"application_id": aid, "target_url": target, "texts": texts, "attachments": [{"name": "cv.pdf", "artifact_id": art["id"]}], "declarations": decl})
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "application-preparation", "status": "DONE"})
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "submission", "status": "RUNNING"})
            err, ap = await call(c, "approval_prepare", {"workflow_id": wid, "action_kind": "application.submit", "target": target, "payload_ref": f"entity:{sub['manifest_id']}"})
            assert not err and ap["state"] == "PENDING" and ap["workflow_state"] == "AWAITING_APPROVAL" and "xnbridge approve" in ap["human_step"]
            state.update(aid=aid, target=target, approval=ap["approval_id"])
            err, bad = await call(c, "execution_record", {"op": "begin", "workflow_id": wid, "capability": "browser.form_fill", "provider": "playwright:browser_click", "idempotency_key": "e2e-s1", "target": target})
            assert err and error_payload(bad)["error"]["code"] == "POLICY_DENIED"
            err, bad = await call(c, "execution_record", {"op": "begin", "workflow_id": wid, "capability": "browser.form_fill", "provider": "playwright:browser_click", "idempotency_key": "e2e-s1", "target": target, "approval_id": ap["approval_id"]})
            assert err and error_payload(bad)["error"]["code"] == "APPROVAL_REJECTED"

    run(part2)
    human = build(home)
    human.approvals.generate_keypair(PASSPHRASE)
    ap_row = human.approvals.get(state["approval"])
    assert ap_row["state"] == "PENDING"

    async def part3():
        async with Client(server_params(home)) as c:
            human_grant(human, state["approval"])
            err, st = await call(c, "approval_status", {"approval_id": state["approval"]})
            assert st["state"] == "GRANTED"
            err, ex = await call(c, "execution_record", {"op": "begin", "workflow_id": wid, "capability": "browser.form_fill", "provider": "playwright:browser_click", "idempotency_key": "e2e-s1", "target": state["target"], "approval_id": state["approval"]})
            assert not err and ex["state"] == "STARTED" and ex["risk"] == "EXTERNAL_WRITE"
            err, ev = await call(c, "evidence_register", {"workflow_id": wid, "claim": "Confirmation page after submit", "origin": "tool_output", "verification": "VERIFIED", "source_ref": state["target"] + "/done", "content": "Thank you, application received"})
            err, fin = await call(c, "execution_record", {"op": "finish", "execution_id": ex["execution_id"], "outcome": "SUCCEEDED", "evidence_ids": [ev["evidence_id"]]})
            assert not err and fin["state"] == "SUCCEEDED"
            err, dup = await call(c, "execution_record", {"op": "begin", "workflow_id": wid, "capability": "browser.form_fill", "provider": "playwright:browser_click", "idempotency_key": "e2e-s2", "target": state["target"], "approval_id": state["approval"]})
            assert err
            await act(c, wid, "tracking.update", {"application_id": state["aid"], "status": "SUBMITTED"})
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "submission", "status": "DONE"})
            await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "tracking", "status": "DONE", "new_state": "COMPLETED"})
            err, got = await call(c, "workflow_get", {"workflow_id": wid, "level": "DETAIL"})
            assert got["state"] == "COMPLETED" and got["detail"]["executions"][0]["state"] == "SUCCEEDED" and len(got["detail"]["executions"]) == 1
            err, rep = await call(c, "domain_action", {"domain": "career", "action": "report.pipeline", "workflow_id": wid})
            assert not err and rep["application"] == {"SUBMITTED": 1}
            err, status = await call(c, "bridge_status", {"workflow_id": wid, "level": "DETAIL"})
            assert status["workflow"]["executions"] == {"SUCCEEDED": 1} and "unavailable" in status["detail"]["metrics"]["tokens"]

    run(part3)
    assert build(home).store.integrity()["ok"]


def test_second_domain_runs_over_the_same_tools(home):
    async def main():
        async with Client(server_params(home)) as c:
            err, wf = await call(c, "workflow_create", {"domain": "research", "title": "lit scan"})
            wid = wf["workflow_id"]
            err, acts = await call(c, "domain_action", {"domain": "research", "action": "?"})
            assert {a["action"] for a in acts["actions"]} == {"sources.add", "sources.verify", "brief.finalize"}
            add = await act(c, wid, "sources.add", {"sources": [{"title": "Attention Is All You Need", "doi": "10.48550/arXiv.1706.03762"}, {"title": "Attention is all you need", "doi": "doi:10.48550/arxiv.1706.03762"}]}, domain="research")
            assert add["added"] == 1 and add["duplicates_merged"] == 1
            err, cp = await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "collect", "status": "DONE"})
            assert not err and cp["next_action"]["stage"] == "verify"
            err, bad = await call(c, "domain_action", {"domain": "career", "action": "match.run", "workflow_id": wid, "payload": {}})
            assert err and error_payload(bad)["error"]["code"] == "VALIDATION_FAILED"

    run(main)


def test_tool_schemas_expose_no_way_to_self_approve(home):
    async def main():
        async with Client(server_params(home)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            props = set()
            for t in tools.values():
                props |= set(t.input_schema.get("properties", {}))
            assert not ({"approved", "approve", "grant", "authorized", "signature", "force", "skip_approval"} & props)
            assert "approval_grant" not in tools and "approval_approve" not in tools

    run(main)


def test_human_approval_cli_refuses_to_run_without_a_terminal(home):
    import os

    env = {**os.environ, "XN_BRIDGE_HOME": str(home)}
    proc = subprocess.run([sys.executable, "-m", "xnbridge.cli", "approve", "apr_x"], input="APPROVE 12345678\n", capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 2 and "interactive terminal" in proc.stderr
    proc = subprocess.run([sys.executable, "-m", "xnbridge.cli", "approval-init"], input="x\nx\n", capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 2
    assert not (home / "approver.key.enc").exists()
