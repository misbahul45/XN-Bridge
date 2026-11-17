from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from . import entities
from .actions import dispatch_action
from .app import Bridge, build
from .domains.career import ats
from .errors import BridgeError
from .routing import Router

REPO_ROOT = Path(__file__).resolve().parents[2]
FIX = REPO_ROOT / "tests" / "fixtures"
SIM_PASSPHRASE = b"dry-run simulated human passphrase"
TARGET = "https://boards.greenhouse.io/northwindlabs/jobs/4001/apply"


class Recorder:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []

    def step(self, name: str, **info: Any) -> None:
        self.steps.append({"step": name, **info})

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})


def _act(bridge: Bridge, wf: str, domain: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = dispatch_action(bridge, domain, action, wf, payload, "DETAIL")
    return {**out.get("detail", {}), **out}


def _expect_error(rec: Recorder, name: str, fn, code: str) -> None:
    try:
        fn()
    except BridgeError as e:
        rec.check(name, e.code == code, f"{e.code}: {e.message[:90]}")
        return
    rec.check(name, False, "no error raised")


def _fixture_get(files: dict[str, str]):
    def get(url: str, *, timeout: float = 20.0, max_bytes: int = ats.MAX_BYTES) -> bytes:
        for key, fname in files.items():
            if key in url:
                return (FIX / "ats" / fname).read_bytes()
        raise AssertionError(f"dry-run has no fixture for {url}")

    return get


def _fixture_endpoint(simulate: str) -> dict[str, Any]:
    if simulate == "timeout":
        return {"ok": False, "error_class": "TRANSPORT", "detail": "fixture endpoint timed out after 30s"}
    return {"ok": True, "confirmation": "Thank you. Your application #FX-1042 was received.", "url": TARGET + "/confirmation"}


def run_career(simulate: str = "success", keep: bool = False) -> dict[str, Any]:
    if not FIX.exists():
        return {"error": "dry-run needs the repository checkout with tests/fixtures", "all_checks_passed": False}
    home = Path(tempfile.mkdtemp(prefix="xnbridge-dryrun-"))
    rec = Recorder()
    real_get = ats.http_get
    import xnbridge.security as sec

    real_resolver = sec.default_resolver
    ats.http_get = _fixture_get({"greenhouse": "greenhouse.json", "lever": "lever.json", "ashby": "ashby.json"})
    sec.default_resolver = lambda host: ["93.184.216.34"]
    try:
        bridge = build(home)
        bridge.settings.policy["limits"]["stale_started_s"] = 120
        wf = bridge.engine.create("career", "dry-run: backend internship in Surabaya")["id"]
        router = Router(availability=lambda cap: bridge.registry.resolve(cap)["status"])
        route = router.route("Cari magang backend di Surabaya, saya punya CV")
        rec.step("route_intent", intent=route.intent, kind=route.kind, layer=route.layer, model_calls=route.model_calls)
        rec.check("routing resolved without a model call", route.model_calls == 0 and route.domain == "career")

        prof = _act(bridge, wf, "career", "profile.ingest", {"path": str(FIX / "cv_good.md")})
        rec.step("profile.ingest", version=prof["version"], skills=len(prof["skills"]), unknown=prof["unknown"])
        _act(bridge, wf, "career", "profile.confirm", {
            "facts": {"full_name": "Rina Kartika", "contact": {"email": "rina.kartika@example.com", "phone": "+62 812 3456 7890"}, "student_status": "enrolled",
                      "graduation_year": 2027, "availability": {"weeks": 26}, "work_authorization": ["Indonesia"], "location": "Surabaya, Indonesia",
                      "languages": {"English": "professional", "Indonesian": "native"}},
            "quote": "SIMULATED USER: I am an enrolled student in Surabaya, available 26 weeks, authorized to work in Indonesia.",
        })
        camp = _act(bridge, wf, "career", "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP", "PKL"], "locations": ["Surabaya"], "scope": "LOCAL"})
        rec.step("campaign.define", queries=camp["query_count"], hard=camp["hard_constraints"])

        comp = _act(bridge, wf, "career", "companies.add", {"companies": [
            {"name": "PT Northwind Labs", "url": "https://www.northwindlabs.example/careers", "source": "search"},
            {"name": "Northwind Labs, Inc.", "url": "https://careers.northwindlabs.example", "source": "directory"},
            {"name": "Acme Robotics", "url": "https://www.linkedin.com/company/acme-robotics", "source": "search"},
            {"name": "Localhost Corp", "url": "http://127.0.0.1:8000", "source": "search"},
        ]})
        rec.step("companies.add", added=comp["added"], merged=comp["merged_duplicates"], rejected=comp["rejected"])
        rec.check("duplicate companies merged, unsafe url rejected", comp["added"] == 2 and comp["merged_duplicates"] == 1 and comp["rejected"] == 1)
        cid = comp["added_list"][0]["company_id"]
        ev = bridge.evidence.register(
            workflow_id=wf, claim="Northwind Labs official careers page", origin="tool_output", requested="VERIFIED", source_ref="https://www.northwindlabs.example/careers",
            content="Northwind Labs careers. We hire interns in Surabaya. https://boards.greenhouse.io/northwindlabs https://jobs.lever.co/northwindlabs https://jobs.ashbyhq.com/northwind", provider="web_search:fetchWebContent", ttl_class="company",
        )
        ver = _act(bridge, wf, "career", "company.verify_domain", {"company_id": cid, "domain": "northwindlabs.example", "evidence_id": ev["id"]})
        rec.check("official domain verified from evidence", ver["verified"] is True)

        fetched = {}
        for name, slug in (("greenhouse", "northwindlabs"), ("lever", "northwindlabs"), ("ashby", "northwind")):
            fetched[name] = _act(bridge, wf, "career", "opportunities.fetch_ats", {"company_id": cid, "ats": name, "slug": slug})
        rec.step("opportunities.fetch_ats", boards={k: {"listed": v["listed"], "kept": v["kept"], "by_status": v["by_status"]} for k, v in fetched.items()})
        again = _act(bridge, wf, "career", "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs"})
        rec.check("re-fetch creates no duplicates", again["added"] == 0)
        with bridge.store.read() as con:
            opps = entities.listing(con, wf, "opportunity")
        flagged = [o for o in opps if o["data"]["flags"]]
        rec.check("injection-bearing posting is quarantined", flagged and all(o["status"] != "OPEN_VERIFIED" for o in flagged), f"{[o['data']['title'] for o in flagged]}")
        rec.check("expired posting detected", any(o["status"] == "EXPIRED" for o in opps))

        match = _act(bridge, wf, "career", "match.run", {})
        rec.step("match.run", tiers=match["tiers"], top=[(t["title"], t["tier"], t["score"]) for t in match["top"]])
        rec.check("US-only listing is ineligible regardless of score", any("Data Science" in i["title"] for i in match["ineligible"]))
        target_opp = next(o for o in opps if "Backend Engineering" in o["data"]["title"])
        rec.check("target listing is OPEN_VERIFIED and ELIGIBLE", target_opp["status"] == "OPEN_VERIFIED" and any(t["opportunity_id"] == target_opp["id"] and t["tier"] == "ELIGIBLE" for t in match["top"]))

        prep = _act(bridge, wf, "career", "application.prepare", {"opportunity_id": target_opp["id"]})
        app_id = prep["application_id"]
        texts = {n: bridge.artifacts.read_text(r["artifact_id"]) for n, r in prep["draft_artifacts"].items()}
        fab = _act(bridge, wf, "career", "draft.check", {"application_id": app_id, "texts": {"probe": "I have 7 years of experience with Terraform at McKinsey."}})
        rec.check("fabricated claims are flagged", fab["verdict"] == "REVIEW")
        chk = _act(bridge, wf, "career", "draft.check", {"application_id": app_id, "texts": texts})
        rec.check("truthful drafts pass the check", chk["verdict"] == "PASS")
        form = _act(bridge, wf, "career", "form.parse_snapshot", {"text": (FIX / "forms" / "snapshot.raw.txt").read_text()})
        plan = _act(bridge, wf, "career", "form.plan", {"application_id": app_id, "fields": form["fields"]})
        rec.step("form.plan", fields=form["field_count"], actions=plan["actions"], declarations_for_user=plan["declarations_for_user"])
        decl = [{"label": d["label"], "answer": "Yes" if "authorized" in d["label"] else "I agree", "user_confirmed": True, "quote": "SIMULATED USER: yes, I confirm"} for d in plan["declarations"]]
        art = bridge.artifacts.put(wf, "attachment", b"%PDF-1.4 dry-run cv", "application/pdf")
        sub = _act(bridge, wf, "career", "submission.prepare", {
            "application_id": app_id, "target_url": TARGET, "texts": texts, "attachments": [{"name": "cv.pdf", "artifact_id": art["id"]}],
            "declarations": decl, "form_plan_digest": plan["plan_digest"],
        })
        rec.step("submission.prepare", manifest=sub["manifest_id"], destination=sub["destination"])
        _expect_error(rec, "submission to an unrelated origin is refused", lambda: _act(bridge, wf, "career", "submission.prepare", {
            "application_id": app_id, "target_url": "https://evil.example/apply", "texts": texts, "declarations": decl}), "POLICY_DENIED")

        spec = bridge.domains.spec("career")
        for st in spec.stages:
            if st.name == "submission":
                bridge.engine.checkpoint(wf, st.name, "RUNNING")
                break
            bridge.engine.checkpoint(wf, st.name, "DONE")
        bridge.approvals.generate_keypair(SIM_PASSPHRASE)
        ap = bridge.approvals.prepare(workflow_id=wf, action_kind="application.submit", target=TARGET, payload_ref=f"entity:{sub['manifest_id']}")
        bridge.engine.transition(wf, "AWAITING_APPROVAL", "approval prepared")
        _expect_error(rec, "unapproved external write is blocked", lambda: bridge.executions.begin(
            workflow_id=wf, capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="dry-0", target=TARGET), "POLICY_DENIED")
        _expect_error(rec, "pending approval cannot be used", lambda: bridge.executions.begin(
            workflow_id=wf, capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="dry-0b", target=TARGET, approval_id=ap["approval_id"]), "APPROVAL_REJECTED")
        priv = serialization.load_pem_private_key(bridge.settings.approver_key.read_bytes(), password=SIM_PASSPHRASE)
        bridge.approvals.grant(ap["approval_id"], priv)
        rec.step("approval", state="GRANTED", note="SIMULATED HUMAN: in real use the user runs `xnbridge approve <id>` in a terminal")

        started = bridge.executions.begin(workflow_id=wf, capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="dry-1", target=TARGET, approval_id=ap["approval_id"])
        rec.check("write-ahead attempt recorded before the external call", started["state"] == "STARTED" and started["risk"] == "EXTERNAL_WRITE")
        _expect_error(rec, "approval is single-use and duplicate submission is blocked", lambda: bridge.executions.begin(
            workflow_id=wf, capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="dry-2", target=TARGET, approval_id=ap["approval_id"]), "CONFLICT")
        result = _fixture_endpoint(simulate)
        if result["ok"]:
            conf = bridge.evidence.register(
                workflow_id=wf, claim="Confirmation page shown after submission", origin="tool_output", requested="VERIFIED",
                source_ref=result["url"], content=result["confirmation"], provider="playwright:browser_snapshot",
            )
            fin = bridge.executions.finish(execution_id=started["execution_id"], outcome="SUCCEEDED", evidence_ids=[conf["id"]])
            rec.check("success is recorded only with verified confirmation evidence", fin["state"] == "SUCCEEDED")
            _act(bridge, wf, "career", "tracking.update", {"application_id": app_id, "status": "SUBMITTED", "note": "fixture endpoint accepted"})
            _act(bridge, wf, "career", "tracking.update", {"application_id": app_id, "status": "ACKNOWLEDGED", "evidence_id": conf["id"]})
        else:
            fin = bridge.executions.finish(execution_id=started["execution_id"], outcome="FAILED", error_class=result["error_class"], detail={"error": result["detail"]})
            rec.check("timeout becomes OUTCOME_UNKNOWN", fin["state"] == "OUTCOME_UNKNOWN" and fin["recovery"]["action"] == "reconcile")
            rec.check("workflow requires reconciliation", bridge.engine.get(wf)["state"] == "RECONCILIATION_REQUIRED")
            _expect_error(rec, "no automatic resubmission after a timeout", lambda: bridge.executions.begin(
                workflow_id=wf, capability="browser.form_fill", provider="playwright:browser_click", idempotency_key="dry-3", target=TARGET), "INVALID_TRANSITION")
            _act(bridge, wf, "career", "tracking.update", {"application_id": app_id, "status": "OUTCOME_UNKNOWN", "note": "timeout; awaiting reconciliation"})
            user = bridge.evidence.register(
                workflow_id=wf, claim="User confirmed the employer portal shows the application", origin="user_statement", requested="VERIFIED",
                source_ref="user:chat", excerpt="SIMULATED USER: I can see application FX-1042 in the portal",
            )
            bridge.executions.reconcile(execution_id=started["execution_id"], outcome="SUCCEEDED", evidence_ids=[user["id"]])
            _act(bridge, wf, "career", "tracking.update", {"application_id": app_id, "status": "SUBMITTED", "note": "reconciled by user statement"})
        bridge.engine.checkpoint(wf, "submission", "DONE")
        bridge.engine.checkpoint(wf, "tracking", "DONE")
        done = bridge.engine.transition(wf, "COMPLETED", "dry-run finished")
        rec.check("workflow completed", done["state"] == "COMPLETED")

        second = build(home)
        resumed = second.engine.resume(wf)
        rec.check("state survives a new process", resumed["state"] == "COMPLETED" and resumed["last_checkpoint"] is not None)
        report = _act(second, wf, "career", "report.pipeline", {})
        rec.step("report.pipeline", **{k: v for k, v in report.items() if isinstance(v, (dict, int)) and k not in ("ok",)})
        with second.store.read() as con:
            n_exec = con.execute("SELECT COUNT(*) FROM executions WHERE risk='EXTERNAL_WRITE'").fetchone()[0]
        rec.check("exactly one external write was ever attempted", n_exec == 1, f"external executions={n_exec}")
        rec.check("database integrity ok", second.store.integrity()["ok"])
        out = {
            "mode": "fixture dry-run: ATS data from tests/fixtures, submission target is a local function, nothing was sent",
            "simulate": simulate,
            "home": str(home) if keep else "(temporary, removed)",
            "steps": rec.steps,
            "checks": rec.checks,
            "checks_passed": sum(c["ok"] for c in rec.checks),
            "checks_total": len(rec.checks),
            "all_checks_passed": all(c["ok"] for c in rec.checks),
        }
        return out
    finally:
        ats.http_get = real_get
        sec.default_resolver = real_resolver
        if not keep:
            shutil.rmtree(home, ignore_errors=True)


def run_research() -> dict[str, Any]:
    home = Path(tempfile.mkdtemp(prefix="xnbridge-dryrun-"))
    rec = Recorder()
    try:
        bridge = build(home)
        wf = bridge.engine.create("research", "dry-run literature scan")["id"]
        added = _act(bridge, wf, "research", "sources.add", {"sources": [
            {"title": "Attention Is All You Need", "doi": "10.48550/arXiv.1706.03762"},
            {"title": "Attention is all you need", "doi": "https://doi.org/10.48550/arxiv.1706.03762"},
            {"title": "Language Models are Few-Shot Learners", "url": "https://arxiv.org/abs/2005.14165?utm_source=x"},
            {"title": "Language models are few shot learners", "url": "https://www.arxiv.org/abs/2005.14165"},
        ]})
        rec.check("sources deduplicated by DOI and canonical URL", added["added"] == 2 and added["duplicates_merged"] == 2)
        bridge.engine.checkpoint(wf, "collect", "DONE")
        with bridge.store.read() as con:
            srcs = entities.listing(con, wf, "source")
        ev = bridge.evidence.register(workflow_id=wf, claim="arXiv abstract page", origin="tool_output", requested="VERIFIED", source_ref="https://arxiv.org/abs/2005.14165", content="Language Models are Few-Shot Learners")
        ok = _act(bridge, wf, "research", "sources.verify", {"source_id": srcs[1]["id"], "evidence_id": ev["id"]})
        weak = bridge.evidence.register(workflow_id=wf, claim="I recall this paper", origin="model_summary", requested="VERIFIED")
        no = _act(bridge, wf, "research", "sources.verify", {"source_id": srcs[0]["id"], "evidence_id": weak["id"]})
        rec.check("only evidence-backed sources become VERIFIED", ok["verified"] is True and no["verified"] is False)
        bridge.engine.checkpoint(wf, "verify", "DONE")
        bad = _act(bridge, wf, "research", "brief.finalize", {"title": "Scaling", "claims": [{"text": "Few-shot learning scales with model size.", "source_ids": [srcs[1]["id"]]}, {"text": "Transformers need no attention.", "source_ids": [srcs[0]["id"]]}]})
        rec.check("unsupported claim blocks the brief", bad["finalized"] is False and bad["unsupported_claims"] == 1)
        good = _act(bridge, wf, "research", "brief.finalize", {"title": "Scaling", "claims": [{"text": "Few-shot learning scales with model size.", "source_ids": [srcs[1]["id"]]}]})
        rec.check("fully supported brief is finalized", good["finalized"] is True)
        bridge.engine.checkpoint(wf, "synthesize", "DONE", new_state="COMPLETED")
        resumed = build(home).engine.resume(wf)
        rec.check("same engine: state persists and resumes", resumed["state"] == "COMPLETED")
        return {"mode": "second domain on the same generic core", "checks": rec.checks, "checks_passed": sum(c["ok"] for c in rec.checks), "checks_total": len(rec.checks), "all_checks_passed": all(c["ok"] for c in rec.checks)}
    finally:
        shutil.rmtree(home, ignore_errors=True)
