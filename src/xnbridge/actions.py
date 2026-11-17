from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from .app import Bridge
from .errors import PolicyDenied, ValidationFailed
from .output import shape
from .spec import Ctx
from .workflow import TERMINAL


def _fmt_validation(e: ValidationError) -> list[dict[str, str]]:
    out = []
    for err in e.errors()[:8]:
        out.append({"field": ".".join(str(p) for p in err["loc"]), "problem": err["msg"]})
    return out


def list_actions(bridge: Bridge, domain: str) -> list[dict[str, Any]]:
    bridge.domains.spec(domain)
    out = []
    for a in bridge.domains.actions(domain):
        fields = list(a.payload_model.model_fields) if a.payload_model else []
        out.append({"action": a.name, "stage": a.stage, "risk": a.risk, "summary": a.summary, "payload": fields})
    return out


def dispatch_action(bridge: Bridge, domain: str, action: str, workflow_id: str | None, payload: dict[str, Any], level: str) -> dict[str, Any]:
    a = bridge.domains.action(domain, action)
    model = a.payload_model
    try:
        validated = model.model_validate(payload) if model else None
    except ValidationError as e:
        raise ValidationFailed(f"invalid payload for {domain}.{action}", details={"errors": _fmt_validation(e), "expected": list(model.model_fields)})
    wf = None
    if a.needs_workflow:
        if not workflow_id:
            raise ValidationFailed(f"{domain}.{action} needs workflow_id")
        wf = bridge.engine.get(workflow_id)
        if wf["domain"] != domain:
            raise ValidationFailed(f"workflow '{workflow_id}' belongs to domain '{wf['domain']}', not '{domain}'")
        if wf["state"] in TERMINAL and a.risk != "READ":
            raise PolicyDenied(f"workflow is {wf['state']}; no further actions", details={"state": wf["state"]})
        if wf["state"] in ("PAUSED", "BLOCKED", "AWAITING_APPROVAL", "RECONCILIATION_REQUIRED") and a.risk != "READ" and not a.safe_when_pending:
            raise PolicyDenied(f"workflow is {wf['state']}; resolve it before running {domain}.{action}", details={"state": wf["state"]})
    started = time.perf_counter()
    result = a.handler(Ctx(bridge, wf), validated)
    bridge.store.metric("action_latency_ms", (time.perf_counter() - started) * 1000, workflow_id, {"action": f"{domain}.{action}"})
    out = shape(
        level,
        summary={"action": f"{domain}.{action}", **result.get("summary", {})},
        detail=result.get("detail"),
        raw=result.get("raw"),
        artifacts=bridge.artifacts,
        workflow_id=workflow_id,
        kind=f"{domain}.{action}",
    )
    if result.get("next"):
        out["next"] = result["next"]
    return out
