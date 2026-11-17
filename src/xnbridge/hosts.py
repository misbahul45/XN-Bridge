"""Small host configuration adapters. They never execute sibling tools."""
from __future__ import annotations

import os
import json
import tomllib
from pathlib import Path

from .discovery import ServerSpec, _spec_from_cfg
from .errors import ValidationFailed


def codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"


def primary_host() -> str:
    choice = os.environ.get("XN_BRIDGE_HOST", "auto")
    if choice not in ("auto", "codex", "claude"):
        raise ValidationFailed("XN_BRIDGE_HOST must be auto, codex or claude")
    return ("codex" if codex_config().is_file() else "claude") if choice == "auto" else choice


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

    host = host or primary_host()
    if host == "codex":
        specs = load_codex_servers(config)
    elif host == "claude":
        specs = load_claude_servers(config, project_mcp)
    else:
        raise ValidationFailed("unsupported host; choose codex or claude")
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
