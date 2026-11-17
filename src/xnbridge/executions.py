from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .approval import ApprovalService
from .config import Settings
from .errors import Conflict, InvalidTransition, LimitExceeded, NotFound, PolicyDenied, ValidationFailed
from .evidence import EvidenceService
from .security import RiskClassifier, digest_obj, origin_of
from .store import Store, jdump, jload, new_id, now_iso, parse_iso
from .workflow import TERMINAL, WorkflowEngine

ERROR_CLASSES = (
    "TRANSPORT", "TOOL_ERROR", "INVALID_OUTPUT", "MISSING_CAPABILITY", "PERMISSION_DENIED",
    "AUTH_REQUIRED", "STALE_EVIDENCE", "USER_INTERVENTION", "UNKNOWN_SIDE_EFFECT",
    "PRECONDITION_FAILED", "ABORTED_BEFORE_SEND", "NONE",
)
NOT_SENT_CLASSES = frozenset({"PRECONDITION_FAILED", "ABORTED_BEFORE_SEND", "PERMISSION_DENIED", "AUTH_REQUIRED", "MISSING_CAPABILITY", "USER_INTERVENTION"})
HEALTH_FAIL_CLASSES = frozenset({"TRANSPORT", "TOOL_ERROR", "INVALID_OUTPUT"})
COOLDOWN_AFTER = 3
COOLDOWN_SECONDS = 300


def _origin_key(target: str) -> str:
    try:
        return origin_of(target)
    except ValidationFailed:
        return target.strip().lower()


def recovery_policy(error_class: str, risk: str, attempts: int, max_retries: int) -> dict[str, Any]:
    if risk == "EXTERNAL_WRITE":
        if error_class in NOT_SENT_CLASSES:
            return {"action": "stop", "reason": "failed before send; a new human approval is required to try again"}
        return {"action": "reconcile", "reason": "external outcome is uncertain; gather confirmation evidence, never resubmit automatically"}
    table = {
        "TRANSPORT": ("retry" if attempts < max_retries else "fallback", "transient transport failure"),
        "TOOL_ERROR": ("fallback", "tool reported an execution error"),
        "INVALID_OUTPUT": ("fallback", "output failed validation; raw output stored, not trusted"),
        "MISSING_CAPABILITY": ("degrade", "no provider; use the capability's degraded behaviour"),
        "PERMISSION_DENIED": ("escalate_user", "permission denied; do not switch to a less restricted provider"),
        "AUTH_REQUIRED": ("escalate_user", "authentication needed; the user must log in, never bypass"),
        "STALE_EVIDENCE": ("retry", "re-fetch fresh evidence"),
        "USER_INTERVENTION": ("escalate_user", "a human step is required (CAPTCHA, consent, login)"),
        "UNKNOWN_SIDE_EFFECT": ("reconcile", "state of the world is unknown; check before acting"),
    }
    action, reason = table.get(error_class, ("fallback", "unclassified failure"))
    if risk == "LOCAL_WRITE" and action == "retry":
        reason += "; retry only with the same idempotency key"
    return {"action": action, "reason": reason}


class ExecutionService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        engine: WorkflowEngine,
        approvals: ApprovalService,
        evidence: EvidenceService,
        classifier: RiskClassifier,
    ):
        self.settings = settings
        self.store = store
        self.engine = engine
        self.approvals = approvals
        self.evidence = evidence
        self.classifier = classifier

    def begin(
        self,
        *,
        workflow_id: str,
        capability: str,
        provider: str | None,
        idempotency_key: str,
        target: str | None = None,
        approval_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise ValidationFailed("idempotency_key is required")
        server, _, tool = (provider or "").partition(":")
        expired = False
        with self.store.tx() as con:
            wf = con.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
            if wf is None:
                raise NotFound(f"workflow '{workflow_id}' not found")
            prior = con.execute("SELECT * FROM executions WHERE workflow_id=? AND idempotency_key=?", (workflow_id, idempotency_key)).fetchone()
            if prior:
                if any(prior[k] != v for k, v in {
                    "capability": capability, "provider": server or None, "tool": tool or None,
                    "target": target, "approval_id": approval_id,
                }.items()):
                    raise Conflict("idempotency key already belongs to a different execution request")
                out = self._public(dict(prior))
                out["replayed"] = True
                if prior["risk"] == "EXTERNAL_WRITE" and prior["state"] in ("STARTED", "OUTCOME_UNKNOWN"):
                    out["warning"] = "this external action was already begun; do not repeat it, reconcile instead"
                return out
            if wf["state"] in TERMINAL:
                raise InvalidTransition(f"workflow is {wf['state']}", details={"state": wf["state"]})
            if wf["deadline_at"] and datetime.now(UTC) > parse_iso(wf["deadline_at"]):
                self.engine._apply_transition(con, workflow_id, wf["state"], "FAILED", "deadline exceeded")
                expired = True
            elif wf["state"] not in ("RUNNING", "AWAITING_APPROVAL"):
                raise InvalidTransition(
                    f"cannot begin an execution while workflow is {wf['state']}",
                    details={"state": wf["state"], "hint": "RECONCILIATION_REQUIRED needs reconcile; BLOCKED/PAUSED need new_state=RUNNING"},
                )
            if not expired:
                return self._begin_tx(con, wf, capability, server, tool, idempotency_key, target, approval_id, dedupe_key)
        raise LimitExceeded("workflow deadline exceeded; workflow marked FAILED")

    def _begin_tx(self, con, wf, capability, server, tool, idem, target, approval_id, dedupe_key) -> dict[str, Any]:
        wid = wf["id"]
        spec = self.engine.domains.spec(wf["domain"])
        stage_risk = None
        try:
            stage_risk = spec.stage(wf["stage"]).risk
        except KeyError:
            pass
        info = self.classifier.classify(server, tool, stage_risk) if server else self.classifier.classify("", "", stage_risk)
        risk = info.risk
        counters = self.engine.counters(con, wid)
        if counters.get("tool_calls", 0) >= self.settings.limit("max_tool_calls"):
            raise LimitExceeded("tool call budget exhausted for this workflow", details={"max_tool_calls": self.settings.limit("max_tool_calls")})
        if capability.startswith("browser.") and counters.get("browser_ops", 0) >= self.settings.limit("max_browser_ops"):
            raise LimitExceeded("browser operation budget exhausted for this workflow")
        failed_before = con.execute(
            "SELECT provider,tool FROM executions WHERE workflow_id=? AND capability=? AND state='FAILED' ORDER BY started_at DESC",
            (wid, capability),
        ).fetchall()
        if len(failed_before) > self.settings.limit("max_retries_per_step") + self.settings.limit("max_provider_switches"):
            raise LimitExceeded("retry budget exhausted for this capability", details={"capability": capability})
        if failed_before and provider_differs(failed_before[0]["provider"], failed_before[0]["tool"], server, tool):
            if counters.get("provider_switches", 0) >= self.settings.limit("max_provider_switches"):
                raise LimitExceeded("provider switch budget exhausted for this workflow")
            self.engine.bump(con, wid, "provider_switches")
        exec_id = new_id("ex")
        payload_digest = None
        if risk == "EXTERNAL_WRITE":
            unattended = not approval_id and self._unattended_enabled()
            if not approval_id and not unattended:
                raise self._approval_required(risk, info.source)
            if not target:
                raise ValidationFailed("target is required for an external write")
            if unattended:
                action_kind, key_target = capability, target
                self._check_unattended(con, target)
            else:
                ap = self.approvals.get(approval_id, con)
                action_kind, key_target = ap["action_kind"], ap["target"]
            key = f"{wid}|{action_kind}|{key_target}"
            live = con.execute(
                "SELECT id,state FROM executions WHERE dedupe_key=? AND risk='EXTERNAL_WRITE' AND state IN ('STARTED','SUCCEEDED','OUTCOME_UNKNOWN','RECONCILED_SUCCEEDED')",
                (key,),
            ).fetchone()
            if live:
                raise Conflict(
                    "duplicate external action blocked: an attempt for this target already exists",
                    details={"existing_execution": live["id"], "existing_state": live["state"]},
                )
            if unattended:
                self.store.audit(con, "bridge", "unattended_external_begin", {"workflow_id": wid, "capability": capability, "target_origin": _origin_key(target)})
            else:
                ap = self.approvals.verify_and_consume(con, approval_id=approval_id, workflow_id=wid, target=target, execution_id=exec_id)
                payload_digest = ap["payload_digest"]
            dedupe = key
        else:
            dedupe = None
        con.execute(
            "INSERT INTO executions(id,workflow_id,capability,provider,tool,risk,idempotency_key,dedupe_key,state,approval_id,payload_digest,target,started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (exec_id, wid, capability, server or None, tool or None, risk, idem, dedupe, "STARTED", approval_id, payload_digest, target, now_iso()),
        )
        self.engine.bump(con, wid, "tool_calls")
        if capability.startswith("browser."):
            self.engine.bump(con, wid, "browser_ops")
        if wf["state"] == "AWAITING_APPROVAL":
            self.engine._apply_transition(con, wid, "AWAITING_APPROVAL", "RUNNING", "approval consumed; execution begun")
        row = dict(con.execute("SELECT * FROM executions WHERE id=?", (exec_id,)).fetchone())
        out = self._public(row)
        out["risk_source"] = info.source
        out["next"] = "perform the action with the host tool, then call execution_record op=finish"
        return out

    def _autonomy(self) -> dict[str, Any]:
        return self.settings.policy.get("autonomy", {})

    def _unattended_enabled(self) -> bool:
        return bool(self._autonomy().get("unattended_external_writes", False))

    def _check_unattended(self, con, target: str) -> None:
        cfg = self._autonomy()
        stop = self.settings.home / str(cfg.get("stop_file", "STOP_EXTERNAL"))
        if stop.exists():
            raise PolicyDenied("unattended external writes are stopped by the owner's stop file", details={"stop_file": stop.name})
        day_start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00")
        rows = con.execute(
            "SELECT target FROM executions WHERE risk='EXTERNAL_WRITE' AND approval_id IS NULL AND started_at>=? AND state!='FAILED'",
            (day_start,),
        ).fetchall()
        per_day = int(cfg.get("max_external_per_day", 25))
        per_origin = int(cfg.get("max_external_per_origin_per_day", 5))
        if len(rows) >= per_day:
            raise LimitExceeded("daily cap for unattended external actions reached", details={"cap": per_day})
        origin = _origin_key(target)
        if sum(1 for r in rows if r["target"] and _origin_key(r["target"]) == origin) >= per_origin:
            raise LimitExceeded("daily cap for unattended external actions to this destination reached", details={"cap": per_origin, "origin": origin})

    def _approval_required(self, risk: str, source: str):
        from .errors import PolicyDenied

        return PolicyDenied(
            "this action is EXTERNAL_WRITE and needs a human-granted approval",
            details={"risk": risk, "classified_by": source, "how": "approval_prepare, then the user runs `xnbridge approve <id>`, then retry with approval_id"},
        )

    def finish(
        self,
        *,
        execution_id: str,
        outcome: str,
        error_class: str = "NONE",
        evidence_ids: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if outcome not in ("SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN"):
            raise ValidationFailed("outcome must be SUCCEEDED, FAILED or OUTCOME_UNKNOWN")
        if error_class not in ERROR_CLASSES:
            raise ValidationFailed(f"error_class must be one of {ERROR_CLASSES}")
        evidence_ids = evidence_ids or []
        notes: list[str] = []
        with self.store.tx() as con:
            row = con.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
            if row is None:
                raise NotFound(f"execution '{execution_id}' not found")
            if row["state"] != "STARTED":
                out = self._public(dict(row))
                out["replayed"] = True
                out["note"] = f"already {row['state']}"
                return out
            for eid in evidence_ids:
                rec = self.evidence.get(eid, con)
                if rec["workflow_id"] != row["workflow_id"]:
                    raise ValidationFailed(f"evidence {eid} belongs to a different workflow")
            final = outcome
            if row["risk"] == "EXTERNAL_WRITE":
                if outcome == "SUCCEEDED":
                    confirmed = [e for e in evidence_ids if self.evidence.usable_as_verified(e, con)[0]]
                    if not confirmed:
                        final = "OUTCOME_UNKNOWN"
                        notes.append("no verified confirmation evidence supplied; recorded as OUTCOME_UNKNOWN, never resubmit")
                elif outcome == "FAILED" and error_class not in NOT_SENT_CLASSES:
                    final = "OUTCOME_UNKNOWN"
                    notes.append(f"error_class {error_class} does not prove the action was not sent; recorded as OUTCOME_UNKNOWN")
            started = parse_iso(row["started_at"])
            latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
            con.execute(
                "UPDATE executions SET state=?, error_class=?, finished_at=?, latency_ms=?, detail_json=? WHERE id=?",
                (final, error_class, now_iso(), latency, jdump({"evidence_ids": evidence_ids, "detail": detail or {}, "notes": notes}), execution_id),
            )
            if row["provider"]:
                self._health(con, row["provider"], final == "SUCCEEDED", error_class)
            if final == "OUTCOME_UNKNOWN" and row["risk"] == "EXTERNAL_WRITE":
                wf = con.execute("SELECT state FROM workflows WHERE id=?", (row["workflow_id"],)).fetchone()
                if wf["state"] == "RUNNING":
                    self.engine._apply_transition(con, row["workflow_id"], "RUNNING", "RECONCILIATION_REQUIRED", f"{execution_id} outcome unknown")
            attempts = con.execute(
                "SELECT COUNT(*) FROM executions WHERE workflow_id=? AND capability=? AND state='FAILED'",
                (row["workflow_id"], row["capability"]),
            ).fetchone()[0]
            self.store.metric_tx(con, "execution_latency_ms", latency, row["workflow_id"], {"capability": row["capability"], "provider": row["provider"], "state": final})
            out = self._public(dict(con.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()))
        out["notes"] = notes
        if final != "SUCCEEDED":
            out["recovery"] = recovery_policy(error_class if final != "OUTCOME_UNKNOWN" or error_class != "NONE" else "UNKNOWN_SIDE_EFFECT", row["risk"], attempts, self.settings.limit("max_retries_per_step"))
        return out

    def reconcile(self, *, execution_id: str, outcome: str, evidence_ids: list[str], note: str = "") -> dict[str, Any]:
        if outcome not in ("SUCCEEDED", "FAILED"):
            raise ValidationFailed("reconcile outcome must be SUCCEEDED or FAILED")
        if not evidence_ids:
            raise ValidationFailed("reconciliation needs at least one evidence id (confirmation page, email, or a user statement)")
        with self.store.tx() as con:
            row = con.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
            if row is None:
                raise NotFound(f"execution '{execution_id}' not found")
            if row["state"] not in ("OUTCOME_UNKNOWN", "STARTED"):
                raise InvalidTransition(f"execution is {row['state']}; nothing to reconcile")
            for e in evidence_ids:
                rec = self.evidence.get(e, con)
                if rec["workflow_id"] != row["workflow_id"]:
                    raise ValidationFailed(f"evidence {e} belongs to a different workflow")
                usable, reason = self.evidence.usable_as_verified(e, con)
                if not usable:
                    raise ValidationFailed(f"evidence {e} cannot reconcile an external outcome: {reason}")
            final = "RECONCILED_SUCCEEDED" if outcome == "SUCCEEDED" else "RECONCILED_FAILED"
            con.execute(
                "UPDATE executions SET state=?, finished_at=?, detail_json=? WHERE id=?",
                (final, now_iso(), jdump({"reconciled_with": evidence_ids, "note": note}), execution_id),
            )
            self.store.audit(con, "bridge", "execution_reconciled", {"execution_id": execution_id, "outcome": final})
            wid = row["workflow_id"]
            wf = con.execute("SELECT state FROM workflows WHERE id=?", (wid,)).fetchone()
            if wf["state"] == "RECONCILIATION_REQUIRED" and not self.engine._unresolved(con, wid):
                self.engine._apply_transition(con, wid, "RECONCILIATION_REQUIRED", "RUNNING", "all executions reconciled")
            out = self._public(dict(con.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()))
        if final == "RECONCILED_FAILED":
            out["next"] = "a retry needs a brand new approval and idempotency key"
        return out

    def list(self, workflow_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.read() as con:
            rows = con.execute("SELECT * FROM executions WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?", (workflow_id, limit)).fetchall()
        return [self._public(dict(r)) for r in rows]

    def _health(self, con, provider: str, ok: bool, error_class: str) -> None:
        now = now_iso()
        row = con.execute("SELECT * FROM server_health WHERE server=?", (provider,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO server_health(server,status,detail,tool_count,consecutive_failures,last_checked_at,last_ok_at) VALUES (?,?,?,?,?,?,?)",
                (provider, "OK" if ok else "FAILED", None, 0, 0 if ok else int(error_class in HEALTH_FAIL_CLASSES), now, now if ok else None),
            )
            return
        if ok:
            con.execute("UPDATE server_health SET consecutive_failures=0, cooldown_until=NULL, last_checked_at=?, last_ok_at=? WHERE server=?", (now, now, provider))
        elif error_class in HEALTH_FAIL_CLASSES:
            n = row["consecutive_failures"] + 1
            cooldown = None
            if n >= COOLDOWN_AFTER:
                cooldown = (datetime.now(UTC) + timedelta(seconds=COOLDOWN_SECONDS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            con.execute("UPDATE server_health SET consecutive_failures=?, cooldown_until=?, last_checked_at=? WHERE server=?", (n, cooldown, now, provider))

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        out = {
            "execution_id": row["id"],
            "workflow_id": row["workflow_id"],
            "capability": row["capability"],
            "provider": f"{row['provider']}:{row['tool']}" if row.get("provider") else None,
            "risk": row["risk"],
            "state": row["state"],
            "idempotency_key": row["idempotency_key"],
            "target": row.get("target"),
            "started_at": row["started_at"],
            "finished_at": row.get("finished_at"),
            "error_class": row.get("error_class"),
        }
        return out


def provider_differs(prev_server: str | None, prev_tool: str | None, server: str | None, tool: str | None) -> bool:
    if not prev_server or not server:
        return False
    return (prev_server, prev_tool) != (server, tool)
