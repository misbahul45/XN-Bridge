from __future__ import annotations

import multiprocessing as mp
from datetime import UTC, datetime, timedelta

import pytest

from xnbridge.app import build
from xnbridge.errors import InvalidTransition, LimitExceeded, NotFound, ValidationFailed
from xnbridge.store import Store, now_iso
from xnbridge.workflow import TRANSITIONS


def test_create_is_planned_and_idempotent(bridge):
    a = bridge.engine.create("research", "t", idempotency_key="k1")
    b = bridge.engine.create("research", "t", idempotency_key="k1")
    assert a["state"] == "PLANNED"
    assert b["id"] == a["id"] and b["replayed"] is True
    assert a["next_action"]["type"] == "run_stage" and a["next_action"]["stage"] == "collect"


def test_unknown_domain_rejected(bridge):
    with pytest.raises(NotFound):
        bridge.engine.create("nope")


@pytest.mark.parametrize("src,dst", [(s, d) for s, ds in TRANSITIONS.items() for d in TRANSITIONS if d not in ds and d != s])
def test_every_illegal_transition_is_rejected(bridge, src, dst):
    wf = bridge.engine.create("research")
    with bridge.store.tx() as con:
        con.execute("UPDATE workflows SET state=? WHERE id=?", (src, wf["id"]))
    with pytest.raises(InvalidTransition):
        bridge.engine.transition(wf["id"], dst, "test")


def test_terminal_states_are_final(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.transition(wf["id"], "CANCELLED", "no")
    for dst in ("RUNNING", "PLANNED", "COMPLETED", "FAILED"):
        with pytest.raises(InvalidTransition):
            bridge.engine.transition(wf["id"], dst)
    with pytest.raises(InvalidTransition):
        bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")


def test_stage_order_enforced(bridge):
    wf = bridge.engine.create("research")
    with pytest.raises(InvalidTransition) as e:
        bridge.engine.checkpoint(wf["id"], "verify", "DONE")
    assert e.value.details["blocking_stage"] == "collect"
    bridge.engine.checkpoint(wf["id"], "collect", "DONE")
    out = bridge.engine.checkpoint(wf["id"], "verify", "DONE")
    assert out["state"] == "RUNNING"


def test_cannot_complete_with_missing_stages_then_can(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "DONE")
    with pytest.raises(InvalidTransition) as e:
        bridge.engine.transition(wf["id"], "COMPLETED")
    assert "verify" in e.value.details["missing_stages"]
    bridge.engine.checkpoint(wf["id"], "verify", "DONE")
    bridge.engine.checkpoint(wf["id"], "synthesize", "DONE", new_state="COMPLETED")
    assert bridge.engine.get(wf["id"])["state"] == "COMPLETED"


def test_awaiting_approval_needs_pending_approval(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    with pytest.raises(InvalidTransition):
        bridge.engine.transition(wf["id"], "AWAITING_APPROVAL")


def test_progress_blocked_while_not_running(bridge):
    wf = bridge.engine.create("research")
    bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    bridge.engine.transition(wf["id"], "PAUSED")
    with pytest.raises(InvalidTransition):
        bridge.engine.checkpoint(wf["id"], "collect", "DONE")
    out = bridge.engine.checkpoint(wf["id"], "collect", "DONE", new_state="RUNNING")
    assert out["state"] == "RUNNING"


def test_checkpoint_idempotency_replays_without_new_checkpoint(bridge):
    wf = bridge.engine.create("research")
    a = bridge.engine.checkpoint(wf["id"], "collect", "DONE", {"n": 1}, idempotency_key="cp-1")
    b = bridge.engine.checkpoint(wf["id"], "collect", "DONE", {"n": 1}, idempotency_key="cp-1")
    assert b["replayed"] is True and b["checkpoint"]["seq"] == a["checkpoint"]["seq"]
    with bridge.store.read() as con:
        assert con.execute("SELECT COUNT(*) FROM checkpoints WHERE workflow_id=?", (wf["id"],)).fetchone()[0] == 1


def test_retry_budget_blocks_workflow(bridge):
    wf = bridge.engine.create("research")
    limit = bridge.settings.limit("max_retries_per_step")
    last = None
    for _ in range(limit + 1):
        last = bridge.engine.checkpoint(wf["id"], "collect", "FAILED")
    assert last["state"] == "BLOCKED"
    assert [s for s in last["steps"] if s["name"] == "collect"][0]["status"] == "BLOCKED"


def test_deadline_fails_workflow(bridge):
    wf = bridge.engine.create("research")
    past = (datetime.now(UTC) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with bridge.store.tx() as con:
        con.execute("UPDATE workflows SET deadline_at=? WHERE id=?", (past, wf["id"]))
    with pytest.raises(LimitExceeded):
        bridge.engine.checkpoint(wf["id"], "collect", "RUNNING")
    assert bridge.engine.get(wf["id"])["state"] == "FAILED"


def test_payload_size_limit(bridge):
    wf = bridge.engine.create("research")
    with pytest.raises(LimitExceeded):
        bridge.engine.checkpoint(wf["id"], "collect", "RUNNING", {"x": "a" * 400_000})


def test_unknown_stage_and_status_rejected(bridge):
    wf = bridge.engine.create("research")
    with pytest.raises(ValidationFailed):
        bridge.engine.checkpoint(wf["id"], "ghost", "RUNNING")
    with pytest.raises(ValidationFailed):
        bridge.engine.checkpoint(wf["id"], "collect", "WHATEVER")


def test_state_survives_process_restart(home):
    b1 = build(home)
    wf = b1.engine.create("research", "persist")
    b1.engine.checkpoint(wf["id"], "collect", "DONE", {"found": 3})
    del b1
    b2 = build(home)
    got = b2.engine.resume(wf["id"])
    assert got["state"] == "RUNNING"
    assert got["last_checkpoint"]["stage"] == "collect"
    assert got["next_action"]["stage"] == "verify"
    assert Store(b2.settings.db_path).integrity()["ok"]


def _worker(home: str, n: int, out):
    from pathlib import Path

    b = build(Path(home))
    ok = 0
    for i in range(n):
        wf = b.engine.create("research", f"w{i}")
        b.engine.checkpoint(wf["id"], "collect", "DONE")
        ok += 1
    out.put(ok)


def test_concurrent_processes_do_not_corrupt_or_lose_writes(home):
    build(home)
    q = mp.get_context("spawn").Queue()
    procs = [mp.get_context("spawn").Process(target=_worker, args=(str(home), 15, q)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0
    assert sum(q.get() for _ in procs) == 60
    b = build(home)
    with b.store.read() as con:
        assert con.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 60
    assert b.store.integrity()["ok"]
