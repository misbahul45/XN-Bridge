from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from xnbridge.routeeval import evaluate, load_cases
from xnbridge.routing import OllamaClassifier
from xnbridge.security import mem_available_mb

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:11434"


def ollama_rss_mb() -> int:
    out = subprocess.run(["ps", "-eo", "rss=,args="], capture_output=True, text=True).stdout
    return sum(int(line.split()[0]) for line in out.splitlines() if len(line.split()) > 1 and "ollama" in line.split()[1]) // 1024


def unload(model: str) -> None:
    req = urllib.request.Request(URL + "/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def summarize(name: str, r: dict) -> dict:
    sev = r["severity"]
    return {
        "name": name,
        "cases": r["cases"],
        "accuracy": r["accuracy"],
        "wrong_confident": r["wrong_confident"],
        "resolved_correctly": sev.get("ok", 0),
        "escalated_to_host": sev.get("escalated", 0) + sev.get("missed_escalated", 0),
        "layers": r["layers"],
        "model_calls": r["model_calls"],
        "latency_ms": r["latency_ms"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=["qwen2.5:1.5b", "gemma3:4b"])
    ap.add_argument("--min-mem-mb", type=int, default=2500)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default=str(ROOT / "bench-out" / "routing-eval.json"))
    args = ap.parse_args()
    sets = {"dev": load_cases(), "heldout": load_cases(ROOT / "tests" / "fixtures" / "routing_heldout.jsonl")}
    report: dict = {"mem_available_mb_start": mem_available_mb(), "runs": []}
    for set_name, cases in sets.items():
        base = evaluate(cases)
        report["runs"].append({**summarize(f"{set_name}/L0-deterministic", base), "failures": base["failures"]})
    for model in args.models:
        avail = mem_available_mb()
        if avail is not None and avail < args.min_mem_mb:
            report["runs"].append({"name": f"hybrid/{model}", "skipped": f"MemAvailable {avail}MB below {args.min_mem_mb}MB"})
            continue
        for set_name, cases in sets.items():
            clf = OllamaClassifier(model, URL, args.timeout, args.min_mem_mb, keep_alive="5m")
            before = mem_available_mb()
            started = time.perf_counter()
            r = evaluate(cases, clf, use_model=True)
            wall = time.perf_counter() - started
            rss = ollama_rss_mb()
            entry = summarize(f"{set_name}/L0+L1 {model}", r)
            entry.update({
                "model": model,
                "model_wall_s": round(wall, 1),
                "model_avg_call_ms": round(clf.total_ms / clf.calls, 1) if clf.calls else None,
                "invalid_outputs": clf.invalid,
                "input_tokens": clf.input_tokens,
                "output_tokens": clf.output_tokens,
                "token_source": "Ollama prompt_eval_count/eval_count (actual runtime counts)",
                "ollama_rss_mb_after": rss,
                "mem_available_mb_before": before,
                "mem_available_mb_after": mem_available_mb(),
                "failures": r["failures"],
            })
            report["runs"].append(entry)
            print(json.dumps({k: v for k, v in entry.items() if k != "failures"}), file=sys.stderr, flush=True)
        unload(model)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
