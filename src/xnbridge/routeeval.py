from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .routing import OllamaClassifier, RouteDecision, Router

DATASET = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "routing_dataset.jsonl"
ESCALATED = ("ambiguous", "unrouted")


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (path or DATASET).read_text(encoding="utf-8").splitlines() if line.strip()]


def make_router(unavailable: set[str] | None = None, classifier: OllamaClassifier | None = None) -> Router:
    down = unavailable or set()
    return Router(availability=lambda cap: "UNAVAILABLE" if cap in down else "AVAILABLE", classifier=classifier)


def judge(case: dict[str, Any], d: RouteDecision) -> tuple[bool, str, str]:
    e = case["expect"]
    ek, k = e["kind"], d.kind
    ok_intents = {e.get("intent")} | set(case.get("also_ok", []))
    if e.get("approval") and d.kind in ("resolved", "degraded") and not d.requires_human_approval:
        return False, "wrong_confident", "approval flag missing on an external write"
    if ek == "escalate":
        if k in ESCALATED:
            return True, "escalated", "escalated to the host model"
        if k == "resolved" and d.intent in ok_intents:
            return True, "ok", "resolved to an acceptable intent"
        return False, "wrong_confident", f"resolved as {k}:{d.intent} but the request is ambiguous"
    if ek == "resolved":
        if k == "resolved" and d.intent in ok_intents:
            return True, "ok", ""
        if k in ESCALATED:
            return False, "missed_escalated", "not recognized; escalated (safe)"
        if k == "needs_info":
            return False, "wrong_other", "asked for more information although the request was complete"
        return False, "wrong_confident", f"got {k}:{d.intent}"
    if ek == "needs_info":
        if k == "needs_info":
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_confident", f"got {k}:{d.intent}"
    if ek == "conflict":
        if k == "conflict":
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_confident", f"got {k}:{d.intent}"
    if ek == "multi":
        got = {p["domain"] for p in d.parts}
        if k == "multi" and got == set(e["domains"]):
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_confident", f"got {k}:{sorted(got)}"
    if ek == "continuation":
        if k == "continuation" and d.intent == e["intent"]:
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_confident", f"got {k}:{d.intent}"
    if ek == "capability":
        if k == "capability" and d.capabilities[:1] == [e["capability"]] and (not e.get("degraded") or d.degraded):
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_confident", f"got {k}:{d.capabilities}"
    if ek == "degraded":
        if k == "degraded" and d.intent == e["intent"]:
            return True, "ok", ""
        return False, "missed_escalated" if k in ESCALATED else "wrong_other", f"got {k}:{d.intent}"
    return False, "wrong_other", f"unknown expectation {ek}"


def active_workflow(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    return ctx if ctx else None


def evaluate(cases: list[dict[str, Any]], classifier: OllamaClassifier | None = None, use_model: bool | None = None) -> dict[str, Any]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    severities: dict[str, int] = defaultdict(int)
    failures: list[dict[str, Any]] = []
    latencies: list[float] = []
    layers: dict[int, int] = defaultdict(int)
    model_calls = 0
    for case in cases:
        router = make_router(set(case.get("unavailable", [])), classifier)
        started = time.perf_counter()
        d = router.route(case["text"], active_workflow=active_workflow(case.get("ctx")), use_model=use_model)
        latencies.append((time.perf_counter() - started) * 1000)
        ok, severity, why = judge(case, d)
        by_cat[case["cat"]].append(ok)
        severities[severity] += 1
        layers[d.layer] += 1
        model_calls += d.model_calls
        if not ok:
            failures.append({"id": case["id"], "cat": case["cat"], "text": case["text"], "expected": case["expect"], "got": f"{d.kind}:{d.intent}", "severity": severity, "why": why, "layer": d.layer})
    total = len(cases)
    correct = sum(sum(v) for v in by_cat.values())
    lat = sorted(latencies)
    return {
        "cases": total,
        "accuracy": round(correct / total, 3),
        "by_category": {c: {"n": len(v), "correct": sum(v), "accuracy": round(sum(v) / len(v), 3)} for c, v in sorted(by_cat.items())},
        "severity": dict(severities),
        "wrong_confident": severities.get("wrong_confident", 0),
        "escalation_rate_to_host": round(sum(1 for f in failures if f["severity"] == "missed_escalated") / total + sum(1 for c in cases if c["expect"]["kind"] == "escalate") / total, 3),
        "layers": dict(layers),
        "model_calls": model_calls,
        "latency_ms": {"p50": round(lat[len(lat) // 2], 2), "p95": round(lat[int(len(lat) * 0.95) - 1], 2), "total": round(sum(lat), 1)},
        "failures": failures,
    }
