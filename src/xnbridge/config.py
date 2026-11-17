from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
BRIDGE_NAME = "xn-bridge"


def default_home() -> Path:
    env = os.environ.get("XN_BRIDGE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file() and (checkout / "src" / "xnbridge").is_dir():
        return (checkout / "data").resolve()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(base) / "xn-bridge").resolve()


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif k == "risk" and isinstance(v, list):
            out[k] = list(v) + list(out.get(k, []))
        else:
            out[k] = v
    return out


def load_toml_default(name: str) -> dict[str, Any]:
    text = (resources.files("xnbridge") / "defaults" / name).read_text(encoding="utf-8")
    return tomllib.loads(text)


@dataclass
class Settings:
    home: Path
    policy: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.home / "bridge.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.home / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def approver_pub(self) -> Path:
        return self.home / "approver.pub"

    @property
    def approver_key(self) -> Path:
        return self.home / "approver.key.enc"

    def ensure_dirs(self) -> None:
        for d in (self.home, self.artifacts_dir, self.logs_dir, self.backups_dir, self.config_dir):
            d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass

    def limit(self, name: str) -> int:
        return int(self.policy["limits"][name])

    def ttl(self, kind: str) -> int:
        t = self.policy["evidence_ttl_s"]
        return int(t.get(kind, t["default"]))


def load_settings(home: Path | None = None) -> Settings:
    home = (home or default_home()).resolve()
    policy = load_toml_default("policy.toml")
    caps = load_toml_default("capabilities.toml")
    for name, target in (("policy.toml", "policy"), ("capabilities.toml", "caps")):
        p = home / "config" / name
        if p.is_file():
            over = tomllib.loads(p.read_text(encoding="utf-8"))
            if target == "policy":
                policy = _deep_merge(policy, over)
            else:
                caps = _deep_merge(caps, over)
    return Settings(home=home, policy=policy, capabilities=caps)
