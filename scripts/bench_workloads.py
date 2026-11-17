from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.career_helpers import FIX, act, confirm_all, mock_ats, new_career, verified_company  # noqa: E402
from xnbridge.app import build  # noqa: E402
from xnbridge.output import estimate_tokens  # noqa: E402
from xnbridge.skills import SkillCatalog  # noqa: E402


def peak_rss_mb() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) // 1024
    return -1


def cj(obj) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str).encode())


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p))], 3)


def timed(fn, n: int) -> dict:
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return {"n": n, "p50_ms": pct(ts, 0.5), "p95_ms": pct(ts, 0.95), "mean_ms": round(statistics.mean(ts), 3)}


class MP:
    def __init__(self):
        self.patches = []

    def setattr(self, target, name, value=None, **kw):
        if isinstance(target, str):
            mod, _, attr = target.rpartition(".")
            import importlib

            obj = importlib.import_module(mod)
            self.patches.append((obj, attr, getattr(obj, attr)))
            setattr(obj, attr, name)
        else:
            self.patches.append((target, name, getattr(target, name)))
            setattr(target, name, value)

    def undo(self):
        for obj, attr, old in reversed(self.patches):
            setattr(obj, attr, old)


def synthetic_board(n: int) -> bytes:
    base = json.loads((FIX / "ats" / "greenhouse.json").read_text())["jobs"][0]
    jobs = []
    for i in range(n):
        j = json.loads(json.dumps(base))
        j["id"] = 100000 + i
        j["title"] = f"{'Backend Engineering Intern' if i % 3 == 0 else 'Senior Engineer'} {i}"
        j["absolute_url"] = f"https://boards.greenhouse.io/northwindlabs/jobs/{100000 + i}"
        jobs.append(j)
    return json.dumps({"jobs": jobs}).encode()


def bench_catalog(report: dict) -> None:
    disc = ROOT / "bench-out" / "discovery-codex.json"
    data = json.loads(disc.read_text()) if disc.exists() else None
    home = Path(tempfile.mkdtemp(prefix="xnb-bench-"))
    b = build(home)
    caps = [c["capability"] for c in b.registry.describe_capabilities()]
    resolved = {c: cj(b.registry.resolve(c)) for c in caps}
    career_caps = ["web.search", "web.fetch", "ats.board_read", "browser.inspect", "browser.form_fill", "document.extract", "document.generate", "workflow.persist", "evidence.store"]
    out = {
        "capability_resolve_bytes": {c: resolved[c] for c in career_caps},
        "capability_resolve_total_bytes_career": sum(resolved[c] for c in career_caps),
    }
    if data:
        total = sum(s["schema_bytes"] for s in data["servers"])
        tools = sum(s["tools"] for s in data["servers"])
        out["naive_all_definitions"] = {"servers": len(data["servers"]), "tools": tools, "bytes": total, "est_tokens": total // 4, "basis": "estimate: UTF-8 bytes/4 of discovered name/inputSchema/description projection, not actual host tokens"}
        out["reduction_factor_vs_resolving_9_capabilities"] = round(total / max(1, out["capability_resolve_total_bytes_career"]), 1)
    report["catalog_exposure"] = out


def bench_levels(report: dict) -> None:
    home = Path(tempfile.mkdtemp(prefix="xnb-bench-"))
    b = build(home)
    mp_ = MP()
    from xnbridge.domains.career import ats

    raw = synthetic_board(300)
    mp_.setattr(ats, "http_get", lambda url, **k: raw)
    mp_.setattr("xnbridge.security.default_resolver", lambda h: ["93.184.216.34"])
    try:
        wf = new_career(b)
        act(b, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP"], "locations": ["Surabaya"], "scope": "LOCAL", "max_companies": 500})
        cid = verified_company(b, wf)
        from xnbridge.actions import dispatch_action

        sizes = {}
        for level in ("SUMMARY", "DETAIL", "RAW_REFERENCE"):
            # Identical initial state for every mode; re-ingesting into one workflow
            # would compare an initial insert against later deduplicated responses.
            b = build(Path(tempfile.mkdtemp(prefix="xnb-level-")))
            wf = new_career(b)
            act(b, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP"], "locations": ["Surabaya"], "scope": "LOCAL"})
            cid = verified_company(b, wf)
            t = time.perf_counter()
            out = dispatch_action(b, "career", "opportunities.fetch_ats", wf, {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs", "only_matching_campaign": True}, level)
            sizes[level] = {"bytes": cj(out), "est_tokens": cj(out) // 4, "ms": round((time.perf_counter() - t) * 1000, 1)}
        report["output_levels"] = {
            "workload": "synthetic scale-up of the Greenhouse fixture: 300 postings, 100 internships kept",
            "naive_raw_into_context": {"bytes": len(raw), "est_tokens": len(raw) // 4},
            "levels": sizes,
            "summary_reduction_factor": round(len(raw) / sizes["SUMMARY"]["bytes"], 1),
            "token_basis": "estimate: chars/4",
        }
    finally:
        mp_.undo()


def bench_skills(report: dict) -> None:
    b = build(Path(tempfile.mkdtemp(prefix="xnb-bench-")))
    cat = SkillCatalog.from_roots([ROOT / "skills"])
    spec = b.domains.spec("career")
    rows = {}
    for st in spec.stages:
        p = cat.plan_load("xn-career", st.references)
        rows[st.name] = {"loaded_bytes": p["bytes_loaded"], "eager_bytes": p["bytes_if_eager"], "ratio": round(p["bytes_loaded"] / p["bytes_if_eager"], 2)}
    avg = statistics.mean(r["ratio"] for r in rows.values())
    audit = None
    audit_path = ROOT / "bench-out" / "runtime-audit.json"
    if audit_path.is_file():
        audit = json.loads(audit_path.read_text())["skills_summary"]
    report["skills"] = {"per_stage": rows, "mean_loaded_over_eager": round(avg, 2), "metadata_bytes_bridge_skills": cat.metadata_bytes(), "host_skill_audit": audit}


def bench_latency(report: dict) -> None:
    home = Path(tempfile.mkdtemp(prefix="xnb-bench-"))
    b = build(home)
    mp_ = MP()
    from xnbridge.domains.career import ats

    raw = synthetic_board(300)
    mp_.setattr(ats, "http_get", lambda url, **k: raw)
    mp_.setattr("xnbridge.security.default_resolver", lambda h: ["93.184.216.34"])
    res: dict = {}
    try:
        t0 = time.process_time()
        res["capability_lookup"] = timed(lambda: b.registry.resolve("web.search"), 300)
        wf = new_career(b)
        res["workflow_create"] = timed(lambda: b.engine.create("research"), 100)
        w2 = b.engine.create("research")["id"]
        b.engine.checkpoint(w2, "collect", "RUNNING")
        res["checkpoint_running"] = timed(lambda: b.engine.checkpoint(w2, "collect", "RUNNING", {"n": 1}), 200)
        res["evidence_register_with_content"] = timed(lambda: b.evidence.register(workflow_id=w2, claim="c", origin="tool_output", requested="VERIFIED", source_ref="https://a.example/x", content="x" * 4000), 100)
        act(b, wf, "campaign.define", {"roles": ["backend"], "categories": ["INTERNSHIP"], "locations": ["Surabaya"], "scope": "LOCAL", "max_companies": 500})
        from tests.career_helpers import ingest_cv

        ingest_cv(b, wf)
        confirm_all(b, wf)
        names = [{"name": f"Company {i} Labs", "url": f"https://company{i}.example"} for i in range(400)] + [{"name": f"PT Company {i} Labs Inc"} for i in range(100)]
        t = time.perf_counter()
        out = act(b, wf, "companies.add", {"companies": names})
        res["company_dedupe_500"] = {"ms": round((time.perf_counter() - t) * 1000, 1), "added": out["added"], "merged": out["merged_duplicates"]}
        cid = verified_company(b, wf)
        t = time.perf_counter()
        f = act(b, wf, "opportunities.fetch_ats", {"company_id": cid, "ats": "greenhouse", "slug": "northwindlabs"})
        res["parse_and_classify_300_postings"] = {"ms": round((time.perf_counter() - t) * 1000, 1), "kept": f["kept"], "raw_bytes": len(raw)}
        t = time.perf_counter()
        m = act(b, wf, "match.run", {})
        res["match_100_opportunities"] = {"ms": round((time.perf_counter() - t) * 1000, 1), "matched": m["matched"]}
        t = time.perf_counter()
        prep = act(b, wf, "application.prepare", {"opportunity_id": m["top"][0]["opportunity_id"]})
        res["document_draft_preparation"] = {"ms": round((time.perf_counter() - t) * 1000, 1), "drafts": len(prep["draft_artifacts"]), "model_calls": 0}
        snap = (FIX / "forms" / "snapshot.raw.txt").read_text()
        res["fixture_form_inspection_parse"] = timed(lambda: act(b, wf, "form.parse_snapshot", {"text": snap}), 30)
        res["workflow_resume"] = timed(lambda: b.engine.resume(wf), 30)
        res["cpu_seconds_total"] = round(time.process_time() - t0, 2)
        res["peak_rss_mb"] = peak_rss_mb()
        res["integrity_ok"] = b.store.integrity()["ok"]
    finally:
        mp_.undo()
    report["latency"] = res


def _hammer(home: str, n: int, q) -> None:
    b = build(Path(home))
    t = []
    for _ in range(n):
        wf = b.engine.create("research")["id"]
        s = time.perf_counter()
        b.engine.checkpoint(wf, "collect", "DONE")
        t.append((time.perf_counter() - s) * 1000)
    q.put(t)


def bench_concurrency(report: dict) -> None:
    home = Path(tempfile.mkdtemp(prefix="xnb-bench-"))
    build(home)
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    started = time.perf_counter()
    procs = [ctx.Process(target=_hammer, args=(str(home), 40, q)) for _ in range(4)]
    for p in procs:
        p.start()
    allt = []
    for _ in procs:
        allt += q.get()
    for p in procs:
        p.join()
    wall = time.perf_counter() - started
    report["concurrency"] = {"processes": 4, "writes": len(allt), "wall_s": round(wall, 2), "checkpoint_p50_ms": pct(allt, 0.5), "checkpoint_p95_ms": pct(allt, 0.95), "integrity_ok": build(home).store.integrity()["ok"]}


CHILD = """
import sys, time
from pathlib import Path
from xnbridge.app import build
b = build(Path(sys.argv[1]))
i = 0
while True:
    wf = b.engine.create("research")["id"]
    b.engine.checkpoint(wf, "collect", "RUNNING")
    ex = b.executions.begin(workflow_id=wf, capability="web.search", provider="web_search:search", idempotency_key=f"k{i}")
    if i % 2 == 0:
        b.executions.finish(execution_id=ex["execution_id"], outcome="SUCCEEDED")
    b.engine.checkpoint(wf, "collect", "DONE")
    i += 1
"""


def bench_recovery(report: dict, cycles: int) -> None:
    ok = 0
    recover_ms = []
    interrupted_total = 0
    for i in range(cycles):
        home = Path(tempfile.mkdtemp(prefix="xnb-kill-"))
        build(home)
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(home)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(random.uniform(0.6, 1.6))
        child.send_signal(signal.SIGKILL)
        child.wait()
        t = time.perf_counter()
        try:
            b = build(home)
            b.settings.policy["limits"]["stale_started_s"] = 0
            integ = b.store.integrity()
            with b.store.read() as con:
                wfs = [r["id"] for r in con.execute("SELECT id FROM workflows")]
            for wf in wfs:
                r = b.engine.resume(wf)
                interrupted_total += len(r["recovered"])
            with b.store.read() as con:
                left = con.execute("SELECT COUNT(*) FROM executions WHERE state='STARTED'").fetchone()[0]
            if integ["ok"] and left == 0:
                ok += 1
        except Exception:
            pass
        recover_ms.append((time.perf_counter() - t) * 1000)
    report["crash_recovery"] = {"kill9_cycles": cycles, "recovered_cleanly": ok, "success_rate": round(ok / cycles, 3), "interrupted_attempts_flagged": interrupted_total, "recovery_p50_ms": pct(recover_ms, 0.5), "recovery_p95_ms": pct(recover_ms, 0.95)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kill-cycles", type=int, choices=range(1, 101), default=30)
    ap.add_argument("--out", default=str(ROOT / "bench-out" / "performance.json"))
    args = ap.parse_args()
    import platform
    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": {"architecture": platform.machine(), "logical_cpus": os.cpu_count()},
                    "host_model_tokens": "unavailable: benchmark executes local code without host inference"}
    for name, fn in (("catalog", bench_catalog), ("levels", bench_levels), ("skills", bench_skills), ("latency", bench_latency), ("concurrency", bench_concurrency)):
        fn(report)
        print(f"[bench] {name} done", file=sys.stderr, flush=True)
    bench_recovery(report, args.kill_cycles)
    print("[bench] recovery done", file=sys.stderr, flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
