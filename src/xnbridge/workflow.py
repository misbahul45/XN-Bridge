from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .errors import InvalidTransition, LimitExceeded, NotFound, ValidationFailed
from .security import canonical_json
from .spec import DomainRegistry, DomainSpec
from .store import Store, jdump, jload, new_id, now_iso, parse_iso

STATES = (
    "CREATED", "PLANNED", "RUNNING", "PAUSED", "BLOCKED", "AWAITING_APPROVAL",
    "RECONCILIATION_REQUIRED", "COMPLETED", "FAILED", "CANCELLED",
)
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"PLANNED", "CANCELLED", "FAILED"}),
    "PLANNED": frozenset({"RUNNING", "CANCELLED", "FAILED"}),
    "RUNNING": frozenset({"PAUSED", "BLOCKED", "AWAITING_APPROVAL", "RECONCILIATION_REQUIRED", "COMPLETED", "FAILED", "CANCELLED"}),
    "PAUSED": frozenset({"RUNNING", "CANCELLED", "FAILED"}),
    "BLOCKED": frozenset({"RUNNING", "FAILED", "CANCELLED"}),
    "AWAITING_APPROVAL": frozenset({"RUNNING", "BLOCKED", "RECONCILIATION_REQUIRED", "CANCELLED", "FAILED"}),
    "RECONCILIATION_REQUIRED": frozenset({"RUNNING", "FAILED", "CANCELLED"}),
    "COMPLETED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}
CHECKPOINT_STATUSES = ("RUNNING", "DONE", "SKIPPED", "FAILED", "BLOCKED")
UNRESOLVED_EXEC = ("STARTED", "OUTCOME_UNKNOWN")


class WorkflowEngine:
    def __init__(self, settings: Settings, store: Store, domains: DomainRegistry):
        self.settings = settings
        self.store = store
        self.domains = domains

    def create(self, domain: str, title: str | None = None, params: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        spec = self.domains.spec(domain)
        if len(spec.stages) > self.settings.limit("max_stages"):
            raise LimitExceeded("domain declares more stages than max_stages")
        params = params or {}
        if len(canonical_json(params).encode()) > self.settings.limit("max_payload_bytes"):
            raise LimitExceeded("params too large")
        with self.store.tx() as con:
            if idempotency_key:
                r = con.execute("SELECT id FROM workflows WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if r:
                    out = self._get(con, r["id"])
                    out["replayed"] = True
                    return out
            wid = new_id("wf")
            ts = now_iso()
            deadline = (datetime.now(UTC) + timedelta(seconds=self.settings.limit("workflow_deadline_s"))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            con.execute(
                "INSERT INTO workflows(id,domain,title,state,stage,spec_version,params_json,counters_json,idempotency_key,created_at,updated_at,deadline_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (wid, domain, title, "CREATED", spec.stages[0].name, spec.version, jdump(params), "{}", idempotency_key, ts, ts, deadline),
            )
            for i, st in enumerate(spec.stages):
                con.execute("INSERT INTO steps(workflow_id,name,ord) VALUES (?,?,?)", (wid, st.name, i))
            self._event(con, wid, "created", None, "CREATED", {"domain": domain})
            self._apply_transition(con, wid, "CREATED", "PLANNED", "planned from domain spec")
            return self._get(con, wid)

    def get(self, workflow_id: str) -> dict[str, Any]:
        with self.store.read() as con:
            return self._get(con, workflow_id)

    def list(self, domain: str | None = None, states: list[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT id,domain,title,state,stage,created_at,updated_at FROM workflows"
        cond, args = [], []
        if domain:
            cond.append("domain=?")
            args.append(domain)
        if states:
            cond.append(f"state IN ({','.join('?' * len(states))})")
            args += states
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self.store.read() as con:
            return [dict(r) for r in con.execute(q, args)]

    def transition(self, workflow_id: str, to_state: str, reason: str = "", idempotency_key: str | None = None) -> dict[str, Any]:
        if to_state not in STATES:
            raise ValidationFailed(f"unknown state '{to_state}'")
        with self.store.tx() as con:
            wf = self._row(con, workflow_id)
            if idempotency_key:
                prior = self._replay(con, workflow_id, idempotency_key)
                if prior is not None:
                    return prior
            self._apply_transition(con, workflow_id, wf["state"], to_state, reason, idempotency_key)
            out = self._get(con, workflow_id)
            if idempotency_key:
                self._store_result(con, workflow_id, idempotency_key, out)
            return out

    def checkpoint(
        self,
        workflow_id: str,
        stage: str,
        status: str,
        data: dict[str, Any] | None = None,
        new_state: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if status not in CHECKPOINT_STATUSES:
            raise ValidationFailed(f"status must be one of {CHECKPOINT_STATUSES}")
        if new_state is not None and new_state not in STATES:
            raise ValidationFailed(f"unknown state '{new_state}'")
        data = data or {}
        if len(canonical_json(data).encode()) > self.settings.limit("max_payload_bytes"):
            raise LimitExceeded("checkpoint data too large; store large content as evidence/artifact and pass the id")
        expired = False
        result: dict[str, Any] | None = None
        with self.store.tx() as con:
            wf = self._row(con, workflow_id)
            if idempotency_key:
                prior = self._replay(con, workflow_id, idempotency_key)
                if prior is not None:
                    return prior
            if wf["state"] in TERMINAL:
                raise InvalidTransition(f"workflow is {wf['state']}; no further checkpoints", details={"state": wf["state"]})
            if self._deadline_passed(wf):
                self._apply_transition(con, workflow_id, wf["state"], "FAILED", "deadline exceeded")
                expired = True
            else:
                result = self._checkpoint_tx(con, wf, stage, status, data, new_state, idempotency_key)
        if expired:
            raise LimitExceeded("workflow deadline exceeded; workflow marked FAILED")
        assert result is not None
        return result

    def _checkpoint_tx(self, con, wf, stage, status, data, new_state, idem) -> dict[str, Any]:
        wid = wf["id"]
        spec = self.domains.spec(wf["domain"])
        try:
            idx = spec.index(stage)
        except KeyError:
            raise ValidationFailed(f"stage '{stage}' not in domain '{spec.name}'", details={"stages": list(spec.stage_names)})
        stage_spec = spec.stages[idx]
        state = wf["state"]
        if state == "PLANNED" and status in ("RUNNING", "DONE", "SKIPPED", "FAILED", "BLOCKED") and new_state is None:
            self._apply_transition(con, wid, "PLANNED", "RUNNING", "first checkpoint")
            state = "RUNNING"
        if state != "RUNNING" and new_state != "RUNNING":
            raise InvalidTransition(
                f"workflow is {state}; set new_state=RUNNING after resolving it before progressing stages",
                details={"state": state},
            )
        if state != "RUNNING" and new_state == "RUNNING":
            self._apply_transition(con, wid, state, "RUNNING", "resumed via checkpoint")
            state = "RUNNING"
            new_state = None
        steps = {r["name"]: dict(r) for r in con.execute("SELECT * FROM steps WHERE workflow_id=?", (wid,))}
        if status in ("DONE", "RUNNING"):
            for earlier in spec.stages[:idx]:
                if not earlier.optional and steps[earlier.name]["status"] not in ("DONE", "SKIPPED"):
                    raise InvalidTransition(
                        f"stage '{earlier.name}' must be DONE or SKIPPED before '{stage}'",
                        details={"blocking_stage": earlier.name, "blocking_status": steps[earlier.name]["status"]},
                    )
        if status == "SKIPPED" and not stage_spec.optional:
            raise InvalidTransition(f"stage '{stage}' is not optional and cannot be skipped")
        attempts = steps[stage]["attempts"]
        blocked_by_retries = False
        if status == "FAILED":
            attempts += 1
            if attempts > self.settings.limit("max_retries_per_step"):
                status = "BLOCKED"
                blocked_by_retries = True
        ts = now_iso()
        started = steps[stage]["started_at"] or (ts if status == "RUNNING" else None)
        finished = ts if status in ("DONE", "SKIPPED", "FAILED", "BLOCKED") else None
        con.execute(
            "UPDATE steps SET status=?, attempts=?, started_at=?, finished_at=?, output_json=? WHERE workflow_id=? AND name=?",
            (status, attempts, started, finished, jdump(data) if data else steps[stage]["output_json"], wid, stage),
        )
        seq = (con.execute("SELECT COALESCE(MAX(seq),0) FROM checkpoints WHERE workflow_id=?", (wid,)).fetchone()[0]) + 1
        steps[stage]["status"] = status
        pointer = next((s.name for s in spec.stages if steps[s.name]["status"] not in ("DONE", "SKIPPED")), spec.stages[-1].name)
        con.execute("UPDATE workflows SET stage=?, updated_at=? WHERE id=?", (pointer, ts, wid))
        cp_id = new_id("cp")
        con.execute(
            "INSERT INTO checkpoints(id,workflow_id,seq,stage,state,data_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (cp_id, wid, seq, stage, state, jdump({"stage": stage, "status": status, "data": data}), ts),
        )
        if blocked_by_retries and new_state is None:
            new_state = "BLOCKED"
        if new_state and new_state != state:
            self._apply_transition(con, wid, state, new_state, f"checkpoint {stage}:{status}", None)
        self._event(con, wid, "checkpoint", None, None, {"stage": stage, "status": status, "seq": seq, "blocked_by_retries": blocked_by_retries}, None)
        out = self._get(con, wid)
        out["checkpoint"] = {"id": cp_id, "seq": seq, "stage": stage, "status": status}
        if blocked_by_retries:
            out["checkpoint"]["note"] = "retry budget exhausted; stage and workflow BLOCKED"
        if idem:
            self._store_result(con, wid, idem, out)
        return out

    def resume(self, workflow_id: str) -> dict[str, Any]:
        stale = timedelta(seconds=self.settings.limit("stale_started_s"))
        changed: list[str] = []
        with self.store.tx() as con:
            wf = self._row(con, workflow_id)
            now = datetime.now(UTC)
            if wf["state"] not in TERMINAL:
                for r in con.execute(
                    "SELECT id,risk,started_at,state FROM executions WHERE workflow_id=? AND state='STARTED'", (workflow_id,)
                ).fetchall():
                    if now - parse_iso(r["started_at"]) < stale:
                        continue
                    if r["risk"] == "EXTERNAL_WRITE":
                        con.execute(
                            "UPDATE executions SET state='OUTCOME_UNKNOWN', error_class='interrupted', finished_at=? WHERE id=?",
                            (now_iso(), r["id"]),
                        )
                        changed.append(f"{r['id']}:OUTCOME_UNKNOWN")
                    else:
                        con.execute(
                            "UPDATE executions SET state='FAILED', error_class='interrupted', finished_at=? WHERE id=?",
                            (now_iso(), r["id"]),
                        )
                        changed.append(f"{r['id']}:FAILED(interrupted)")
            unresolved = self._unresolved(con, workflow_id)
            external_unresolved = [u for u in unresolved if u["risk"] == "EXTERNAL_WRITE"]
            wf = self._row(con, workflow_id)
            if external_unresolved and wf["state"] in ("RUNNING", "AWAITING_APPROVAL"):
                self._apply_transition(con, workflow_id, wf["state"], "RECONCILIATION_REQUIRED", "unresolved external write on resume")
            elif wf["state"] == "PAUSED" and not external_unresolved:
                self._apply_transition(con, workflow_id, "PAUSED", "RUNNING", "resume")
            elif wf["state"] == "PLANNED":
                pass
            out = self._get(con, workflow_id)
            last = con.execute("SELECT id,seq,stage,state,created_at FROM checkpoints WHERE workflow_id=? ORDER BY seq DESC LIMIT 1", (workflow_id,)).fetchone()
            out["last_checkpoint"] = dict(last) if last else None
            out["unresolved_executions"] = unresolved
            out["recovered"] = changed
            out["replay_safe"] = self._replay_safe_stages(con, out)
            return out

    def next_action(self, wf: dict[str, Any], con=None) -> dict[str, Any]:
        state = wf["state"]
        spec = self.domains.spec(wf["domain"])
        if state in TERMINAL:
            return {"type": "none", "reason": f"workflow {state}"}
        if state == "AWAITING_APPROVAL":
            return {"type": "await_human_approval", "instruction": "ask the user to run `xnbridge approve <approval_id>` in their own terminal, then call approval_status"}
        if state == "RECONCILIATION_REQUIRED":
            return {"type": "reconcile", "instruction": "an external action has an unknown outcome; gather confirmation evidence and call execution_record op=reconcile; never re-run it"}
        if state == "BLOCKED":
            return {"type": "blocked", "instruction": "resolve the blocker (see steps) then workflow_checkpoint new_state=RUNNING"}
        if state == "PAUSED":
            return {"type": "paused", "instruction": "call workflow_resume"}
        step_status = {s["name"]: s["status"] for s in wf["steps"]}
        for st in spec.stages:
            if step_status[st.name] not in ("DONE", "SKIPPED"):
                return {
                    "type": "run_stage",
                    "stage": st.name,
                    "goal": st.goal,
                    "capabilities": list(st.capabilities),
                    "optional_capabilities": list(st.optional_capabilities),
                    "load_references": list(st.references),
                    "risk": st.risk,
                    "actions": list(st.actions),
                    "optional": st.optional,
                }
        return {"type": "complete", "instruction": "all stages done: workflow_checkpoint new_state=COMPLETED"}

    def bump(self, con, workflow_id: str, key: str, n: int = 1) -> int:
        row = con.execute("SELECT counters_json FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            raise NotFound(f"workflow '{workflow_id}' not found")
        counters = jload(row["counters_json"], {})
        counters[key] = counters.get(key, 0) + n
        con.execute("UPDATE workflows SET counters_json=?, updated_at=? WHERE id=?", (jdump(counters), now_iso(), workflow_id))
        return counters[key]

    def counters(self, con, workflow_id: str) -> dict[str, Any]:
        row = con.execute("SELECT counters_json FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        return jload(row["counters_json"], {}) if row else {}

    def _row(self, con, workflow_id: str) -> sqlite3.Row:
        r = con.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if r is None:
            raise NotFound(f"workflow '{workflow_id}' not found")
        return r

    def _get(self, con, workflow_id: str) -> dict[str, Any]:
        wf = self._row(con, workflow_id)
        steps = [
            {"name": r["name"], "status": r["status"], "attempts": r["attempts"]}
            for r in con.execute("SELECT name,status,attempts FROM steps WHERE workflow_id=? ORDER BY ord", (workflow_id,))
        ]
        out = {
            "id": wf["id"],
            "domain": wf["domain"],
            "title": wf["title"],
            "state": wf["state"],
            "stage": wf["stage"],
            "params": jload(wf["params_json"], {}),
            "counters": jload(wf["counters_json"], {}),
            "created_at": wf["created_at"],
            "updated_at": wf["updated_at"],
            "deadline_at": wf["deadline_at"],
            "steps": steps,
        }
        out["next_action"] = self.next_action(out)
        return out

    def _deadline_passed(self, wf) -> bool:
        return bool(wf["deadline_at"]) and datetime.now(UTC) > parse_iso(wf["deadline_at"])

    def _event(self, con, wid: str, kind: str, from_state, to_state, detail, idem: str | None = None) -> None:
        con.execute(
            "INSERT INTO workflow_events(workflow_id,ts,kind,from_state,to_state,detail_json,idempotency_key) VALUES (?,?,?,?,?,?,?)",
            (wid, now_iso(), kind, from_state, to_state, jdump(detail) if detail is not None else None, idem),
        )

    def _replay(self, con, wid: str, idem: str) -> dict[str, Any] | None:
        r = con.execute("SELECT detail_json FROM workflow_events WHERE workflow_id=? AND idempotency_key=?", (wid, idem)).fetchone()
        if r is None:
            return None
        stored = jload(r["detail_json"], {})
        result = stored.get("result") if isinstance(stored, dict) else None
        if result is None:
            fresh = self._get(con, wid)
            fresh["replayed"] = True
            return fresh
        result["replayed"] = True
        return result

    def _store_result(self, con, wid: str, idem: str, result: dict[str, Any]) -> None:
        con.execute(
            "UPDATE workflow_events SET detail_json=? WHERE workflow_id=? AND idempotency_key=?",
            (jdump({"result": result}), wid, idem),
        )
        exists = con.execute("SELECT 1 FROM workflow_events WHERE workflow_id=? AND idempotency_key=?", (wid, idem)).fetchone()
        if not exists:
            self._event(con, wid, "idempotent_result", None, None, {"result": result}, idem)

    def _unresolved(self, con, workflow_id: str) -> list[dict[str, Any]]:
        rows = con.execute(
            f"SELECT id,capability,provider,tool,risk,state,target,started_at,error_class FROM executions WHERE workflow_id=? AND state IN ({','.join('?' * len(UNRESOLVED_EXEC))})",
            (workflow_id, *UNRESOLVED_EXEC),
        ).fetchall()
        return [dict(r) for r in rows]

    def _replay_safe_stages(self, con, wf: dict[str, Any]) -> list[str]:
        spec = self.domains.spec(wf["domain"])
        status = {s["name"]: s["status"] for s in wf["steps"]}
        return [s.name for s in spec.stages if s.risk == "READ" and status[s.name] in ("RUNNING", "PENDING", "FAILED")]

    def _apply_transition(self, con, wid: str, from_state: str, to_state: str, reason: str, idem: str | None = None) -> None:
        if to_state == from_state:
            raise InvalidTransition(f"workflow already {from_state}", details={"state": from_state})
        allowed = TRANSITIONS.get(from_state, frozenset())
        if to_state not in allowed:
            raise InvalidTransition(
                f"illegal transition {from_state} -> {to_state}",
                details={"from": from_state, "to": to_state, "allowed": sorted(allowed)},
            )
        self._preconditions(con, wid, from_state, to_state)
        con.execute("UPDATE workflows SET state=?, updated_at=? WHERE id=?", (to_state, now_iso(), wid))
        self._event(con, wid, "transition", from_state, to_state, {"reason": reason}, idem)

    def _preconditions(self, con, wid: str, from_state: str, to_state: str) -> None:
        wf = self._row(con, wid)
        if to_state == "COMPLETED":
            spec = self.domains.spec(wf["domain"])
            steps = {r["name"]: r["status"] for r in con.execute("SELECT name,status FROM steps WHERE workflow_id=?", (wid,))}
            missing = [s.name for s in spec.stages if not s.optional and steps.get(s.name) not in ("DONE", "SKIPPED")]
            if missing:
                raise InvalidTransition("cannot complete: required stages not done", details={"missing_stages": missing})
            if self._unresolved(con, wid):
                raise InvalidTransition("cannot complete: unresolved executions exist", details={"unresolved": self._unresolved(con, wid)})
        if to_state == "AWAITING_APPROVAL":
            n = con.execute("SELECT COUNT(*) FROM approvals WHERE workflow_id=? AND state IN ('PENDING','GRANTED')", (wid,)).fetchone()[0]
            if n == 0:
                raise InvalidTransition("AWAITING_APPROVAL needs at least one pending or granted approval")
        if to_state == "RECONCILIATION_REQUIRED":
            if not [u for u in self._unresolved(con, wid)]:
                raise InvalidTransition("RECONCILIATION_REQUIRED needs an unresolved execution")
        if from_state == "RECONCILIATION_REQUIRED" and to_state == "RUNNING":
            if self._unresolved(con, wid):
                raise InvalidTransition("unresolved executions must be reconciled first", details={"unresolved": self._unresolved(con, wid)})
        if to_state == "RUNNING" and from_state in ("PLANNED", "PAUSED", "BLOCKED", "AWAITING_APPROVAL") and self._deadline_passed(wf):
            raise InvalidTransition("deadline exceeded; workflow cannot run")
