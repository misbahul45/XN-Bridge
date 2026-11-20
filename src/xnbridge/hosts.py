"""Small host configuration adapters. They never execute sibling tools."""
from __future__ import annotations

import os
import json
import tomllib
from pathlib import Path

from .discovery import ServerSpec, _spec_from_cfg
from .errors import ValidationFailed
from .security import canonical_json

JSON_HOST_SOURCES = {
    "gemini": (".gemini/settings.json", "mcpServers"),
    "qwen": (".qwen/settings.json", "mcpServers"),
    "kiro": (".kiro/settings/mcp.json", "mcpServers"),
    "cursor": (".cursor/mcp.json", "mcpServers"),
    "pi": (".pi/agent/mcp.json", "mcpServers"),
    "copilot": (".copilot/mcp-config.json", "mcpServers"),
    "vscode": (".config/Code/User/mcp.json", "servers"),
    "zed": (".config/zed/settings.json", "context_servers"),
    "opencode": (".config/opencode/opencode.json", "mcp"),
}
HOST_ORDER = ("claude", "codex", *JSON_HOST_SOURCES)
HOST_CHOICES = ("all", *HOST_ORDER)


def codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"


def _env_host() -> str:
    choice = os.environ.get("XN_BRIDGE_HOST", "auto")
    if choice != "auto" and choice not in HOST_CHOICES:
        raise ValidationFailed("XN_BRIDGE_HOST must be auto, all or one of: " + ", ".join(HOST_ORDER))
    return choice


def primary_host() -> str:
    choice = _env_host()
    if choice in ("codex", "claude"):
        return choice
    return "codex" if codex_config().is_file() else "claude"


def fingerprint_scope() -> str:
    choice = _env_host()
    return "all" if choice in ("auto", "all") else choice


def _json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        data = json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))
    return data if isinstance(data, dict) else {}


def _generic_spec(name: str, cfg: object, source: str) -> ServerSpec | None:
    if not isinstance(cfg, dict) or cfg.get("disabled") is True or cfg.get("enabled") is False:
        return None
    command = cfg.get("command")
    args = [str(a) for a in (cfg.get("args") or [])]
    if isinstance(command, list):
        command, args = (str(command[0]) if command else None), [str(a) for a in command[1:]] + args
    url = cfg.get("url") or cfg.get("httpUrl")
    if not command and not url:
        return None
    env = cfg.get("env") or cfg.get("environment") or {}
    return _spec_from_cfg(name, {"type": "http" if url else "stdio", "command": command, "args": args, "env": env, "url": url}, source)


def load_json_host_servers(host: str, path: Path | None = None) -> list[ServerSpec]:
    rel, key = JSON_HOST_SOURCES[host]
    data = _json_file(path or Path.home() / rel)
    section = data.get(key)
    if not isinstance(section, dict):
        return []
    specs = [_generic_spec(name, cfg, f"{host}-user") for name, cfg in section.items()]
    return [s for s in specs if s is not None]


def load_all_host_servers() -> list[ServerSpec]:
    from .discovery import load_claude_servers

    found = load_claude_servers(None, None) + load_codex_servers()
    for host in JSON_HOST_SOURCES:
        found += load_json_host_servers(host)
    unique: dict[tuple[str, str], ServerSpec] = {}
    for spec in found:
        if spec.name != "xn-bridge":
            unique.setdefault((spec.name, canonical_json(spec.material())), spec)
    return [unique[k] for k in sorted(unique)]


def probe_targets(specs: list[ServerSpec]) -> list[ServerSpec]:
    rank = {h: i for i, h in enumerate(HOST_ORDER)}
    chosen: dict[str, ServerSpec] = {}
    for spec in sorted(specs, key=lambda s: (rank.get(s.source.split("-")[0], len(rank)), s.name)):
        chosen.setdefault(spec.name, spec)
    return sorted(chosen.values(), key=lambda s: s.name)


def load_codex_servers(path: Path | None = None) -> list[ServerSpec]:
    path = path or codex_config()
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    specs = []
    for name, cfg in data.get("mcp_servers", {}).items():
        if not cfg.get("enabled", True):
            continue
        cfg = dict(cfg)
        cfg["env"] = {**{k: os.environ[k] for k in cfg.get("env_vars", []) if k in os.environ}, **cfg.get("env", {})}
        spec = _spec_from_cfg(name, cfg, "codex-user")
        # Changes to host permission filters invalidate the catalog without retaining credentials.
        spec.permissions = {k: cfg[k] for k in ("enabled_tools", "disabled_tools", "approval_policy") if k in cfg}
        specs.append(spec)
    return specs


def load_host_servers(host: str | None = None, *, config: Path | None = None, project_mcp: Path | None = None) -> list[ServerSpec]:
    from .discovery import load_claude_servers

    host = host or fingerprint_scope()
    if host == "all":
        specs = load_all_host_servers()
    elif host == "codex":
        specs = load_codex_servers(config)
    elif host == "claude":
        specs = load_claude_servers(config, project_mcp or Path(__file__).resolve().parents[2] / ".mcp.json")
    elif host in JSON_HOST_SOURCES:
        specs = load_json_host_servers(host, config)
    else:
        raise ValidationFailed("unsupported host; choose all, codex, claude or " + ", ".join(JSON_HOST_SOURCES))
    # The bridge is a local capability, not a sibling provider to probe recursively.
    return [s for s in specs if s.name != "xn-bridge"]


def codex_registration(text: str, entry: dict) -> str:
    """Append one validated table; preserve every existing byte and refuse replacement."""
    data = tomllib.loads(text)
    existing = data.get("mcp_servers", {}).get("xn-bridge")
    if existing is not None:
        if all(existing.get(k) == v for k, v in entry.items()) and existing.get("enabled", True):
            return text
        raise ValidationFailed("Codex already has a different xn-bridge entry; refusing to replace it")
    addition = '\n[mcp_servers.xn-bridge]\n'
    for k in ("command", "args"):
        addition += f"{k} = {json.dumps(entry[k])}\n"
    addition += '\n[mcp_servers.xn-bridge.env]\n'
    for k, v in entry.get("env", {}).items():
        addition += f'{json.dumps(k)} = {json.dumps(v)}\n'
    result = text.rstrip("\n") + "\n" + addition
    merged = tomllib.loads(result)
    assert merged["mcp_servers"].pop("xn-bridge") == entry
    # Existing tables, models, permissions and credential references must remain identical.
    if not data.get("mcp_servers"):
        data["mcp_servers"] = {}
    assert merged == data
    return result
