from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio

from .security import canonical_json, digest_obj, redact


@dataclass
class ServerSpec:
    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    source: str = "claude-user"
    permissions: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        args = []
        hide_next = False
        for a in self.args:
            key = a.split("=", 1)[0].lower().replace("_", "-")
            secret_flag = key.startswith("-") and any(x in key for x in ("token", "secret", "password", "passwd", "api-key", "apikey", "authorization"))
            if hide_next:
                args.append("<redacted>")
                hide_next = False
            elif secret_flag:
                args.append(key + "=<redacted>" if "=" in a else a)
                hide_next = "=" not in a
            else:
                args.append(redact(a))
        safe_url = None
        if self.url:
            parts = urlsplit(self.url)
            host = parts.hostname or ""
            host = f"[{host}]" if ":" in host else host
            safe_url = f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "") + parts.path
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": args,
            "url": safe_url,
            "env_keys": sorted(self.env),
            "source": self.source,
            "permissions": self.permissions,
        }

    def material(self) -> dict[str, Any]:
        d = self.public()
        d.pop("source", None)
        return d


@dataclass
class ToolMeta:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    title: str | None = None
    annotations: dict[str, Any] | None = None

    @property
    def schema_digest(self) -> str:
        return digest_obj({"input": self.input_schema or {}, "output": self.output_schema, "annotations": self.annotations})

    @property
    def desc_digest(self) -> str:
        return digest_obj({"d": self.description or "", "t": self.title or ""})

    def summary(self, limit: int = 160) -> str:
        text = " ".join((self.description or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class ServerProbe:
    server: str
    transport: str
    status: str
    detail: str = ""
    protocol_version: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    tools: list[ToolMeta] = field(default_factory=list)
    elapsed_ms: int = 0

    def schema_bytes(self) -> int:
        return sum(len(canonical_json({"n": t.name, "d": t.description, "s": t.input_schema}).encode("utf-8")) for t in self.tools)


def load_claude_servers(claude_json: Path | None = None, project_mcp: Path | None = None) -> list[ServerSpec]:
    specs: dict[str, ServerSpec] = {}
    cj = claude_json or Path.home() / ".claude.json"
    if cj.is_file():
        data = json.loads(cj.read_text(encoding="utf-8"))
        for name, cfg in (data.get("mcpServers") or {}).items():
            specs[name] = _spec_from_cfg(name, cfg, "claude-user")
    if project_mcp and project_mcp.is_file():
        data = json.loads(project_mcp.read_text(encoding="utf-8"))
        for name, cfg in (data.get("mcpServers") or {}).items():
            specs[name] = _spec_from_cfg(name, cfg, "project")
    return list(specs.values())


def _spec_from_cfg(name: str, cfg: dict[str, Any], source: str) -> ServerSpec:
    kind = cfg.get("type") or ("http" if cfg.get("url") else "stdio")
    if kind in ("http", "sse"):
        return ServerSpec(name=name, transport="http", url=cfg.get("url"), source=source)
    return ServerSpec(
        name=name,
        transport="stdio",
        command=cfg.get("command"),
        args=list(cfg.get("args") or []),
        env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
        source=source,
    )


def host_fingerprint(specs: list[ServerSpec]) -> str:
    material = sorted((s.material() for s in specs), key=lambda d: d["name"])
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()[:24]


def _tool_from_sdk(t: Any) -> ToolMeta:
    ann = getattr(t, "annotations", None)
    ann_d = ann.model_dump(exclude_none=True) if hasattr(ann, "model_dump") else (dict(ann) if ann else None)
    return ToolMeta(
        name=t.name,
        description=t.description or "",
        input_schema=dict(getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}),
        output_schema=(getattr(t, "output_schema", None) or getattr(t, "outputSchema", None)) or None,
        title=getattr(t, "title", None),
        annotations=ann_d,
    )


async def _list_all_tools(client: Any, max_pages: int = 100) -> list[ToolMeta]:
    tools: list[ToolMeta] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(max_pages):
        res = await client.list_tools(cursor=cursor) if cursor else await client.list_tools()
        tools.extend(_tool_from_sdk(t) for t in res.tools)
        cursor = getattr(res, "next_cursor", None) or getattr(res, "nextCursor", None)
        if not cursor:
            return tools
        if cursor in seen_cursors:
            raise ValueError("server repeated its tools/list cursor; catalog is incomplete")
        seen_cursors.add(cursor)
    raise ValueError("tools/list pagination exceeded max_pages; catalog is incomplete")


def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for e in exc.exceptions:
            leaves.extend(_leaf_exceptions(e))
        return leaves
    return [exc]


def _classify_failure(exc: BaseException) -> tuple[str, str]:
    leaves = _leaf_exceptions(exc)
    parts = []
    for e in leaves:
        status = getattr(getattr(e, "response", None), "status_code", None)
        parts.append(f"{type(e).__name__}: {e}" + (f" (http {status})" if status else ""))
    text = "; ".join(parts) or str(exc)
    low = text.lower()
    if any(k in low for k in ("http 401", "http 403", "401", "unauthorized", "forbidden", "authentication", "oauth", "invalid_token")):
        return "AUTH_REQUIRED", redact(text)[:300]
    return "FAILED", redact(text)[:300]


async def _attempt(spec: ServerSpec, mode: str, timeout_s: float, env_overrides, cwd, errfile) -> ServerProbe:
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client

    probe = ServerProbe(server=spec.name, transport=spec.transport, status="FAILED")
    with anyio.fail_after(timeout_s):
        if spec.transport == "stdio":
            env = {**spec.env, **(env_overrides or {})}
            params = StdioServerParameters(command=spec.command, args=spec.args, env=env or None, cwd=cwd)
            target = Client(stdio_client(params, errlog=errfile), mode=mode)
        else:
            target = Client(spec.url, mode=mode)
        async with target as client:
            probe.protocol_version = client.protocol_version
            info = client.server_info
            probe.server_name = getattr(info, "name", None)
            probe.server_version = getattr(info, "version", None)
            caps = client.server_capabilities
            probe.capabilities = caps.model_dump(exclude_none=True) if hasattr(caps, "model_dump") else {}
            probe.tools = await _list_all_tools(client)
            allowed = spec.permissions.get("enabled_tools")
            denied = set(spec.permissions.get("disabled_tools", []))
            probe.tools = [t for t in probe.tools if (allowed is None or t.name in allowed) and t.name not in denied]
            probe.status = "OK"
    return probe


async def probe_server(
    spec: ServerSpec,
    *,
    timeout_s: float = 60.0,
    env_overrides: dict[str, str] | None = None,
    cwd: str | None = None,
    log_dir: Path | None = None,
) -> ServerProbe:
    started = anyio.current_time()
    fail = ServerProbe(server=spec.name, transport=spec.transport, status="FAILED")
    if spec.transport == "stdio" and not spec.command:
        fail.detail = "no command configured"
        return fail
    if spec.transport == "http" and not spec.url:
        fail.detail = "no url configured"
        return fail
    modes = ("auto", "legacy") if spec.transport == "stdio" else ("auto",)
    result: ServerProbe = fail
    notes: list[str] = []
    for mode in modes:
        errfile = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") if spec.transport == "stdio" else None
        try:
            result = await _attempt(spec, mode, timeout_s, env_overrides, cwd, errfile)
            if mode == "legacy":
                notes.append("connected only with the legacy initialize handshake (server rejects the modern discover probe)")
            break
        except TimeoutError:
            result = ServerProbe(server=spec.name, transport=spec.transport, status="FAILED", detail=f"timeout after {timeout_s:.0f}s")
            break
        except Exception as e:
            status, detail = _classify_failure(e)
            tail = ""
            if errfile is not None:
                try:
                    errfile.seek(0)
                    tail = redact(" ".join(errfile.read()[-300:].split()))
                except Exception:
                    tail = ""
            result = ServerProbe(server=spec.name, transport=spec.transport, status=status, detail=(detail + (" | stderr: " + tail if tail else ""))[:600])
        finally:
            if errfile is not None:
                errfile.close()
    if notes and result.status == "OK":
        result.detail = "; ".join(notes)
    result.elapsed_ms = int((anyio.current_time() - started) * 1000)
    return result


async def discover(
    specs: list[ServerSpec],
    *,
    only: list[str] | None = None,
    probe_http: bool = False,
    timeout_s: float = 60.0,
    isolate: dict[str, dict[str, str]] | None = None,
    scratch_cwd: str | None = None,
    on_progress=None,
) -> list[ServerProbe]:
    out: list[ServerProbe] = []
    for spec in specs:
        if only and spec.name not in only:
            continue
        if spec.transport == "http" and not probe_http:
            out.append(ServerProbe(server=spec.name, transport="http", status="NOT_PROBED", detail="remote http server; authenticated tools are only visible inside the host"))
            continue
        if on_progress:
            on_progress(spec.name)
        probe = await probe_server(
            spec,
            timeout_s=timeout_s,
            env_overrides=(isolate or {}).get(spec.name),
            cwd=scratch_cwd if spec.transport == "stdio" else None,
        )
        out.append(probe)
    return out


def isolation_env(scratch: Path) -> dict[str, dict[str, str]]:
    s = str(scratch)
    return {
        "xninetzy": {
            "MCP_HOST_DATA_DIR": s,
            "MCP_HOST_SQLITE_PATH": os.path.join(s, "xninetzy-isolated.sqlite3"),
            "SQLITE_PATH": os.path.join(s, "xninetzy-isolated.sqlite3"),
        },
        "xn-motion": {"XN_MOTION_DATA_DIR": os.path.join(s, "xn-motion")},
    }
