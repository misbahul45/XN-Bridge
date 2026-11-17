"""Read-only, credential-free audit. Generated reports stay in ignored local data."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from xnbridge.hosts import codex_config, load_host_servers
from xnbridge.security import redact
from xnbridge.skills import read_meta, audit

ROOT = Path(__file__).resolve().parents[1]


def command(args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=12)
        return {"status": "VERIFIED_RUNTIME", "exit": p.returncode, "output": redact(p.stdout + p.stderr).strip()[:16000]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "UNKNOWN", "reason": type(e).__name__}


def collect():
    mem = {k.rstrip(":"): int(v.split()[0]) for k, v in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}
    hosts = {}
    for host, cfg in (("codex", codex_config()), ("claude", Path.home() / ".claude.json")):
        try:
            specs = load_host_servers(host, config=cfg)
            hosts[host] = {"path": str(cfg), "version": command([host, "--version"]), "servers": [s.public() for s in specs]}
        except (OSError, ValueError) as e:
            hosts[host] = {"status": "UNKNOWN", "reason": type(e).__name__}
    metas = []
    seen = set()
    for root in [Path.home() / ".codex/skills", Path.home() / ".agents/skills", ROOT / "skills"]:
        candidates = []
        visited = set()
        for current, dirs, files in os.walk(root, followlinks=True):
            actual = Path(current).resolve()
            if actual in visited:
                dirs[:] = []
                continue
            visited.add(actual)
            if "SKILL.md" in files:
                candidates.append(Path(current) / "SKILL.md")
        for p in candidates:
            if p.resolve() in seen:
                continue
            seen.add(p.resolve())
            m = read_meta(p)
            if m:
                metas.append(m)
    skills = [{"name": m.name, "description": m.description[:500], "path": str(m.path), "body_bytes": m.body_bytes,
               "required": m.required, "hardcoded_tools": m.hardcoded_tools, "references": len(m.references)} for m in metas]
    packages = {}
    for name in ["mcp", "pydantic", "cryptography", "pytest", "httpx", "anyio"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    models = command(["ollama", "list"])
    config = {}
    if codex_config().is_file():
        import tomllib
        d = tomllib.loads(codex_config().read_text())
        config = {k: d.get(k) for k in ["model", "model_provider", "model_reasoning_effort"]}
    disk = shutil.disk_usage(ROOT)
    return {"generated_at": datetime.now(UTC).isoformat(), "evidence_class": "VERIFIED_RUNTIME",
            "os": platform.freedesktop_os_release(), "kernel": platform.release(), "architecture": platform.machine(),
            "cpu": command(["lscpu"]), "gpu": command(["lspci", "-nn"]), "logical_cpus": os.cpu_count(),
            "memory_kib": {k: mem[k] for k in ["MemTotal", "MemAvailable", "SwapTotal", "SwapFree"]},
            "disk_bytes": {"total": disk.total, "free": disk.free}, "loadavg": os.getloadavg(),
            "pressure": {n: Path(f"/proc/pressure/{n}").read_text() for n in ["cpu", "memory", "io"]},
            "limits": {"nofile": resource.getrlimit(resource.RLIMIT_NOFILE), "nproc": resource.getrlimit(resource.RLIMIT_NPROC)},
            "python": sys.version, "packages": packages,
            "runtimes": {n: command([n, "--version"]) for n in ["node", "npm", "pnpm", "bun", "uv", "git", "opencode", "cursor"] if shutil.which(n)},
            "hosts": hosts, "configured_model": config, "local_models": models,
            "skills_summary": audit(metas), "skills": skills,
            "research_package_files_found": [p.name for p in ROOT.glob("*.md") if p.name != "README.md"],
            "host_tokens": "UNAVAILABLE: no inference request made; host API exposes usage only for inference turns"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench-out/runtime-audit.json")
    args = ap.parse_args()
    out = collect()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=list) + "\n")
    print(json.dumps({"report": args.out, "os": out["os"]["PRETTY_NAME"], "skills": len(out["skills"]),
                      "hosts": {k: len(v.get("servers", [])) for k, v in out["hosts"].items()}}))
