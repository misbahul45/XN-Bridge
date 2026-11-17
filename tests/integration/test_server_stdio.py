from __future__ import annotations

import json
import subprocess
import sys
import time

import anyio
import pytest
from mcp import Client

from tests.helpers import call, error_payload, listening_sockets, server_params

EXPECTED_TOOLS = {
    "bridge_status", "capability_resolve", "route_intent", "workflow_create", "workflow_get", "workflow_checkpoint",
    "workflow_resume", "evidence_register", "evidence_get", "approval_prepare", "approval_status", "execution_record", "domain_action",
}


def run(coro_fn):
    return anyio.run(coro_fn)


def test_t01_initialization_over_real_stdio(home):
    async def main():
        async with Client(server_params(home)) as c:
            assert c.server_info.name == "xn-bridge"
            assert c.protocol_version
            assert c.server_capabilities.tools is not None
            return c.protocol_version

    assert run(main)


def test_t02_tool_discovery_has_valid_metadata(home):
    async def main():
        async with Client(server_params(home)) as c:
            tools = (await c.list_tools()).tools
            assert {t.name for t in tools} == EXPECTED_TOOLS
            for t in tools:
                assert t.description and len(t.description) < 260
                assert t.input_schema["type"] == "object"
                assert t.annotations is not None
            ro = {t.name for t in tools if t.annotations.read_only_hint}
            assert {"bridge_status", "workflow_get", "approval_status", "evidence_get", "route_intent", "capability_resolve"} <= ro
            assert not ({"workflow_checkpoint", "execution_record", "approval_prepare"} & ro)

    run(main)


def test_t03_invalid_arguments_rejected(home):
    async def main():
        async with Client(server_params(home)) as c:
            err, data = await call(c, "workflow_get", {"workflow_id": 5})
            assert err
            err, data = await call(c, "workflow_get", {})
            assert err
            err, data = await call(c, "bridge_status", {"level": "EVERYTHING"})
            assert err
            err, data = await call(c, "evidence_register", {"workflow_id": "x", "claim": "c", "origin": "oracle"})
            assert err
            err, data = await call(c, "execution_record", {"op": "explode"})
            assert err
            err, data = await call(c, "workflow_create", {"domain": "nope"})
            assert err and error_payload(data)["error"]["code"] == "NOT_FOUND"
            err, data = await call(c, "workflow_create", {"domain": "research", "params": {"x": "a" * 400_000}})
            assert err and error_payload(data)["error"]["code"] == "LIMIT_EXCEEDED"
            err, data = await call(c, "execution_record", {"op": "begin"})
            assert err and error_payload(data)["error"]["code"] == "VALIDATION_FAILED"

    run(main)


def test_workflow_roundtrip_and_resume_across_server_restarts(home):
    async def first():
        async with Client(server_params(home)) as c:
            err, wf = await call(c, "workflow_create", {"domain": "research", "title": "restart"})
            assert not err
            err, cp = await call(c, "workflow_checkpoint", {"workflow_id": wf["workflow_id"], "stage": "collect", "status": "DONE", "data": {"n": 2}})
            assert not err and cp["state"] == "RUNNING"
            return wf["workflow_id"]

    async def second(wid):
        async with Client(server_params(home)) as c:
            err, res = await call(c, "workflow_resume", {"workflow_id": wid})
            assert not err
            assert res["last_checkpoint"]["stage"] == "collect"
            assert res["next_action"]["stage"] == "verify"
            err, bad = await call(c, "workflow_checkpoint", {"workflow_id": wid, "stage": "synthesize", "status": "DONE"})
            assert err and error_payload(bad)["error"]["code"] == "INVALID_TRANSITION"

    wid = run(first)
    run(lambda: second(wid))


def test_stdout_carries_only_protocol_and_shutdown_is_graceful(home):
    env = {"XN_BRIDGE_HOME": str(home), "PATH": "/usr/bin:/bin"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "xnbridge.server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True,
    )
    try:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        msg = json.loads(line)
        assert msg["jsonrpc"] == "2.0" and msg["id"] == 1 and msg["result"]["serverInfo"]["name"] == "xn-bridge"
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        listed = json.loads(proc.stdout.readline())
        assert len(listed["result"]["tools"]) == 13
        assert listening_sockets(proc.pid) == []
        proc.stdin.close()
        t0 = time.time()
        assert proc.wait(timeout=10) == 0
        assert time.time() - t0 < 10
        remaining = proc.stdout.read()
        for ln in remaining.splitlines():
            json.loads(ln)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_t23_no_listener_and_no_network_requirement_while_serving_calls(home):
    async def main():
        async with Client(server_params(home)) as c:
            await call(c, "workflow_create", {"domain": "research"})
            await call(c, "bridge_status", {"level": "DETAIL"})
            err, st = await call(c, "bridge_status", {"level": "DETAIL"})
            assert not err and st["transport"] == "stdio"

    run(main)
