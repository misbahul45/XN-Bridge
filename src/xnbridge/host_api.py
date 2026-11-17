"""Bounded access to the installed Codex stdio API, without inference or config writes.

Codex owns the sibling MCP connections. This adapter only reads inventory/events.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .discovery import ServerProbe, ServerSpec, _tool_from_sdk, isolation_env
from .errors import Unavailable, ValidationFailed
from .hosts import load_codex_servers
from .security import redact

ROOT = Path(__file__).resolve().parents[2]
MAX_LINE = 8 * 1024 * 1024


class CodexHost:
    def __init__(self, *, servers: list[str], cwd: Path = ROOT, bridge_home: Path | None = None):
        executable = shutil.which("codex")
        if not executable:
            raise Unavailable("Codex executable is unavailable")
        specs = {s.name: s for s in load_codex_servers()}
        unknown = set(servers) - set(specs) - ({"xn-bridge"} if bridge_home else set())
        if unknown or any(not re.fullmatch(r"[A-Za-z0-9_-]+", n) for n in {*specs, *servers}):
            raise ValidationFailed("unsupported or unconfigured Codex server selection")
        self._scratch = tempfile.TemporaryDirectory(prefix="xnbridge-host-audit-")
        scratch = Path(self._scratch.name)
        cmd = [executable, "app-server", "--stdio", "-c", "analytics.enabled=false"]
        for name in specs:
            cmd += ["-c", f"mcp_servers.{name}.enabled=" + ("true" if name in servers else "false")]
        overrides = isolation_env(scratch)
        for name in servers:
            # Never put configured credential values into process arguments.
            for key, value in {"UV_OFFLINE": "1", "npm_config_offline": "true", **overrides.get(name, {})}.items():
                cmd += ["-c", f"mcp_servers.{name}.env.{key}={json.dumps(value)}"]
        if bridge_home:
            for key, value in {"enabled": True, "command": str(ROOT / ".venv/bin/python"), "args": ["-m", "xnbridge.server"]}.items():
                cmd += ["-c", f"mcp_servers.xn-bridge.{key}={json.dumps(value)}"]
            cmd += ["-c", f"mcp_servers.xn-bridge.env.XN_BRIDGE_HOME={json.dumps(str(bridge_home))}"]
        self.stderr = tempfile.TemporaryFile(mode="w+")
        env = {**os.environ, "UV_OFFLINE": "1", "npm_config_offline": "true"}
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                                         text=True, cwd=cwd, env=env)
        except OSError:
            self.stderr.close()
            self._scratch.cleanup()
            raise Unavailable("failed to start the installed Codex host")
        self.lines = queue.Queue(maxsize=8)
        self.notifications = []
        self.seq = 0
        self.thread_id = None
        self._closing = threading.Event()

        def reader():
            while not self._closing.is_set():
                line = self.proc.stdout.readline(MAX_LINE + 1)
                value = line if line and len(line) <= MAX_LINE else None
                while not self._closing.is_set():
                    try:
                        self.lines.put(value, timeout=0.2)
                        break
                    except queue.Full:
                        pass
                if value is None:
                    break
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()

    def _receive(self, deadline):
        try:
            line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
        except queue.Empty as e:
            raise Unavailable("Codex host request exceeded its deadline") from e
        if line is None:
            self.stderr.seek(0)
            raise Unavailable("Codex host exited or exceeded message limits: " + redact(self.stderr.read())[-1000:])
        try:
            msg = json.loads(line)
        except ValueError as e:
            raise Unavailable("Codex returned invalid protocol data") from e
        if not isinstance(msg, dict):
            raise Unavailable("Codex returned a non-object protocol message")
        return msg

    def _event(self, msg):
        if "method" in msg and "id" in msg:
            # This adapter never grants permissions, credentials or elicitation requests.
            self.proc.stdin.write(json.dumps({"id": msg["id"], "error": {"code": -32601, "message": "inventory adapter does not grant approvals"}}) + "\n")
            self.proc.stdin.flush()
        elif msg.get("method") == "mcpServer/startupStatus/updated":
            p = msg.get("params", {})
            self.notifications.append({"name": p.get("name"), "status": p.get("status")})
            self.notifications = self.notifications[-256:]

    def request(self, method, params, timeout=30):
        self.seq += 1
        try:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params}) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            raise Unavailable("Codex host input channel is closed") from e
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._receive(deadline)
            if msg.get("id") == self.seq:
                if "error" in msg:
                    raise Unavailable(f"Codex rejected {method}: " + redact(str(msg["error"]))[:500])
                return msg.get("result", {})
            self._event(msg)
        raise Unavailable("Codex host request exceeded its deadline")

    def start(self, cwd=ROOT, timeout=30):
        self.request("initialize", {"clientInfo": {"name": "xn-bridge-catalog", "version": "0.1.0"},
                                   "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}}, timeout=timeout)
        thread = self.request("thread/start", {"cwd": str(cwd), "ephemeral": True, "approvalPolicy": "never", "sandbox": "read-only"}, timeout=timeout)
        self.thread_id = thread["thread"]["id"]
        return self.thread_id

    def inventory(self, server: str | None = None, timeout=30):
        return list_inventory(self.request, self.thread_id, server=server, timeout=timeout)

    def close(self):
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self._closing.set()
        self.reader.join(timeout=2)
        self.proc.stdout.close()
        self.stderr.close()
        self._scratch.cleanup()


def list_inventory(request, thread_id, *, server=None, timeout=30, max_pages=100):
    rows, seen = [], set()
    cursor = None
    deadline = time.monotonic() + timeout
    for _ in range(max_pages):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable("Codex catalog pagination exceeded its deadline")
        result = request("mcpServerStatus/list", {"threadId": thread_id, "serverName": server, "cursor": cursor, "limit": 25}, timeout=remaining)
        page = result.get("data")
        if not isinstance(page, list) or len(rows) + len(page) > 10000:
            raise ValidationFailed("invalid or excessive host catalog rows")
        rows.extend(page)
        cursor = result.get("nextCursor")
        if not cursor:
            return rows
        if cursor in seen:
            raise ValidationFailed("Codex host repeated its catalog cursor")
        seen.add(cursor)
    raise ValidationFailed("Codex catalog pagination exceeded max_pages")


def host_probe(row: dict, spec: ServerSpec) -> ServerProbe:
    from mcp.types import Tool

    state = row.get("runtimeStatus")
    error = row.get("toolsError")
    info = row.get("serverInfo") or {}
    status = "OK" if state == "connected" and not error and info else "NOT_READY"
    if state == "authenticationRequired":
        status = "AUTH_REQUIRED"
    elif state in ("failed", "cancelled", "disabled") or error:
        status = "FAILED"
    probe = ServerProbe(spec.name, spec.transport, status, detail=redact(str(error or state or "runtime status unavailable"))[:300],
                        server_name=info.get("name"), server_version=info.get("version"), capabilities=row.get("serverCapabilities") or {})
    if status == "OK":
        try:
            raw = row.get("tools", {})
            if not isinstance(raw, dict) or len(raw) > 10000:
                raise ValueError("invalid tool map")
            for key, value in raw.items():
                tool = _tool_from_sdk(Tool.model_validate(value))
                if tool.name != key:
                    raise ValueError("tool map key differs from tool name")
                if tool.name in spec.permissions.get("disabled_tools", []):
                    continue
                allowed = spec.permissions.get("enabled_tools")
                if allowed is None or tool.name in allowed:
                    probe.tools.append(tool)
        except (ValueError, TypeError) as e:
            probe.status, probe.detail, probe.tools = "FAILED", "host tool catalog failed schema validation", []
    # The host API does not expose the negotiated MCP protocol revision.
    return probe
