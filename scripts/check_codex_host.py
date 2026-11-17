"""Exercise the installed Codex host over its own stdio app-server API, without inference.

Only XN-Bridge is enabled in this invocation. No persistent host settings are changed.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from xnbridge.host_api import CodexHost

ROOT = Path(__file__).resolve().parents[1]


class Host(CodexHost):
    def __init__(self, state: Path):
        super().__init__(servers=["xn-bridge"], cwd=ROOT, bridge_home=state)


def check() -> dict:
    with tempfile.TemporaryDirectory(prefix="xnbridge-codex-host-") as tmp:
        host = Host(Path(tmp))
        started = time.perf_counter()
        try:
            init = host.request("initialize", {"clientInfo": {"name": "xn-bridge-acceptance", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}})
            skill_inventory = host.request("skills/list", {"cwds": [str(ROOT)], "forceReload": True})
            skill_names = {s["name"] for group in skill_inventory.get("data", []) for s in group.get("skills", [])}
            assert {"xn-bridge", "xn-career"} <= skill_names, "project coordination skills are not visible to Codex"
            thread = host.request("thread/start", {"cwd": str(ROOT), "ephemeral": True, "approvalPolicy": "never", "sandbox": "read-only"})
            tid = thread["thread"]["id"]
            inventory = host.request("mcpServerStatus/list", {"threadId": tid, "serverName": "xn-bridge", "limit": 10})
            def call(tool, arguments):
                result = host.request("mcpServer/tool/call", {"threadId": tid, "server": "xn-bridge", "tool": tool, "arguments": arguments})
                # App-server returns the MCP result directly.
                if result.get("isError"):
                    raise RuntimeError(str(result))
                return result.get("structuredContent") or json.loads(result["content"][0]["text"])
            status = call("bridge_status", {})
            wf = call("workflow_create", {"domain": "research", "idempotency_key": "real-codex-host"})
            cp = call("workflow_checkpoint", {"workflow_id": wf["workflow_id"], "stage": "collect", "status": "DONE"})
            resumed = call("workflow_resume", {"workflow_id": wf["workflow_id"]})
            # Direct sibling calls bypass bridge bookkeeping. Demonstrate only a harmless call.
            bypass = call("bridge_status", {"workflow_id": wf["workflow_id"], "level": "DETAIL"})
            assert status["transport"] == "stdio"
            assert cp["next_action"]["stage"] == resumed["next_action"]["stage"] == "verify"
            assert bypass["detail"]["metrics"]["executions"] == {}
            rows = inventory.get("data", [])
            return {"ok": True, "host": "codex", "host_version": subprocess.check_output([shutil.which("codex"), "--version"], text=True).strip(),
                    "host_user_agent": init.get("userAgent"), "discovered_servers": [{"name": s.get("name"), "tools": len(s.get("tools", {}))} for s in rows],
                    "calls": 5, "model_calls": 0, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "native_skills_discovered": sorted(skill_names & {"xn-bridge", "xn-career"}),
                    "checkpoint_resume": "PASS", "direct_tool_bookkeeping_bypass": "VERIFIED: direct host calls do not require bridge execution records; real submissions remain manual"}
        finally:
            host.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench-out/codex-host.json")
    args = ap.parse_args()
    result = check()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
