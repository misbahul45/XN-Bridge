from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import shutil
import sqlite3
import sys
import time
import unicodedata
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from . import __version__
from .app import build
from .discovery import discover as run_discover
from .discovery import host_fingerprint, isolation_env
from .hosts import codex_config, codex_registration, load_host_servers, primary_host
from .errors import BridgeError, ValidationFailed
from .security import mem_available_mb, self_rss_mb
from .store import jload

REPO_ROOT = Path(__file__).resolve().parents[2]


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _need_tty(action: str) -> bool:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    print(f"refusing to {action}: this command needs an interactive terminal operated by a human", file=sys.stderr)
    return False


def cmd_approval_init(args) -> int:
    if not _need_tty("create the approver key"):
        return 2
    bridge = build()
    p1 = getpass.getpass("New approver passphrase: ")
    p2 = getpass.getpass("Repeat passphrase: ")
    if p1 != p2 or len(p1) < 10:
        print("passphrases differ or are shorter than 10 characters", file=sys.stderr)
        return 1
    fp = bridge.approvals.generate_keypair(p1.encode())
    print(f"approver key created. fingerprint: {fp}")
    print(f"private key (encrypted): {bridge.settings.approver_key}")
    return 0


def _terminal(text: str) -> str:
    return "".join(repr(c)[1:-1] if unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" else c for c in text)


def _render_payload(bridge, approval: dict[str, Any]) -> bool:
    try:
        kind, _, ident = approval["payload_ref"].partition(":")
        with bridge.store.read() as con:
            digest = bridge.approvals.digest_for_ref(con, approval["workflow_id"], approval["payload_ref"])
            if digest != approval["payload_digest"]:
                raise ValidationFailed("payload changed after preparation")
            if kind == "entity":
                row = con.execute("SELECT data_json FROM entities WHERE id=? AND workflow_id=?", (ident, approval["workflow_id"])).fetchone()
                data = jload(row["data_json"]) if row else None
            else:
                _, content = bridge.artifacts.read(ident)
                data = json.loads(content)
        if not isinstance(data, dict):
            raise ValidationFailed("interactive approval requires a structured JSON payload")
        if not isinstance(data.get("texts"), dict):
            text = json.dumps(data, indent=2, ensure_ascii=False)
            if len(text.encode()) > bridge.settings.limit("max_payload_bytes"):
                raise ValidationFailed("payload is too large for complete terminal review")
            print(_terminal(text))
            return True
        for name in ("company", "position", "destination", "channel"):
            print(_terminal(f"  {name}: {data.get(name)}"))
        for name, ref in data["texts"].items():
            meta, raw = bridge.artifacts.read(ref["artifact_id"])
            if meta["bytes"] > bridge.settings.limit("max_payload_bytes"):
                raise ValidationFailed("prepared text is too large for complete terminal review")
            print(_terminal(f"\n--- {name} (sha256 {ref['digest']}) ---\n" + raw.decode("utf-8")))
        for attachment in data.get("attachments", []):
            print(_terminal(f"\nattachment: {attachment['name']} sha256 {attachment['digest']} {attachment['bytes']} bytes"))
        for declaration in data.get("declarations", []):
            print(_terminal(f"declaration: {declaration['label']} => {declaration['answer']}"))
        print(_terminal(str(data.get("irreversible", ""))))
        return True
    except (BridgeError, ValueError, KeyError, TypeError) as e:
        print("Cannot review the complete payload; approval refused. " + _terminal(str(e)), file=sys.stderr)
        return False


def cmd_approve(args) -> int:
    if not _need_tty("grant an approval"):
        return 2
    bridge = build()
    try:
        ap = bridge.approvals.status(args.approval_id)
    except BridgeError as e:
        print(e.message, file=sys.stderr)
        return 1
    print("=" * 72)
    print(f" APPROVAL {ap['approval_id']}   state={ap['state']}   expires in {ap['expires_in_s']}s")
    print(_terminal(f" action  : {ap['action_kind']}"))
    print(_terminal(f" target  : {ap['target']}"))
    print(f" digest  : {ap['payload_digest']}")
    if not _render_payload(bridge, ap):
        return 1
    print("=" * 72)
    if ap["state"] != "PENDING":
        print(f"nothing to do: approval is {ap['state']}")
        return 1
    short = ap["payload_digest"][:8]
    answer = input(f"Type  APPROVE {short}  to grant exactly this payload, or REJECT: ").strip()
    if answer.upper() == "REJECT":
        bridge.approvals.reject(args.approval_id)
        print("rejected")
        return 0
    if answer != f"APPROVE {short}":
        print("confirmation text did not match; nothing granted")
        return 1
    pw = getpass.getpass("Approver passphrase: ")
    try:
        priv = serialization.load_pem_private_key(bridge.settings.approver_key.read_bytes(), password=pw.encode())
    except (ValueError, TypeError):
        print("wrong passphrase; nothing granted", file=sys.stderr)
        return 1
    try:
        out = bridge.approvals.grant(args.approval_id, priv)
    except BridgeError as e:
        print(e.message, file=sys.stderr)
        return 1
    print(f"granted. valid until {out['expires_at']}. It can be used exactly once, for this payload and this target only.")
    return 0


def cmd_approvals(args) -> int:
    bridge = build()
    with bridge.store.read() as con:
        rows = [dict(r) for r in con.execute("SELECT id,workflow_id,state,action_kind,target,expires_at FROM approvals ORDER BY created_at DESC LIMIT ?", (args.limit,))]
    _print(rows)
    return 0


def cmd_discover(args) -> int:
    bridge = build()
    project_mcp = Path(args.project_mcp) if args.project_mcp else REPO_ROOT / ".mcp.json"
    specs = load_host_servers(args.host, config=Path(args.config) if args.config else None, project_mcp=project_mcp)
    if getattr(args, "via_host", False):
        if args.host != "codex" or args.config:
            raise ValidationFailed("native host inventory currently supports the actual Codex configuration only")
        from .host_catalog import sync_host_catalog
        report = sync_host_catalog(bridge, specs, only=args.only, timeout=args.timeout,
                                   watch_seconds=args.watch_seconds, poll_interval=args.poll_interval,
                                   progress=lambda name: print(f"[host catalog] {name}", file=sys.stderr, flush=True))
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _print(report)
        return 0 if report["ok"] else 1
    if getattr(args, "watch_seconds", 0):
        raise ValidationFailed("watch mode requires --via-host")
    scratch = bridge.settings.home / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    fp = host_fingerprint(specs)

    def progress(name: str) -> None:
        print(f"[discover] probing {name} ...", file=sys.stderr, flush=True)

    probes = asyncio.run(
        run_discover(
            specs, only=args.only or None, probe_http=args.probe_http, timeout_s=args.timeout,
            isolate=isolation_env(scratch), scratch_cwd=str(scratch), on_progress=progress,
        )
    )
    delta = bridge.registry.ingest(probes, host_fp=fp, active_servers=[s.name for s in specs])
    report = {
        "host": args.host,
        "host_fingerprint": fp,
        "servers": [
            {"server": p.server, "transport": p.transport, "status": p.status, "protocol": p.protocol_version, "version": p.server_version,
             "tools": len(p.tools), "schema_bytes": p.schema_bytes(), "elapsed_ms": p.elapsed_ms, "detail": p.detail}
            for p in probes
        ],
        "delta": {k: len(v) for k, v in delta.items()},
        "changed_tools": delta["changed"],
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _print(report)
    return 0


def cmd_catalog(args) -> int:
    bridge = build()
    if args.action == "health":
        if not args.server or not args.status or not args.detail:
            raise ValidationFailed("catalog health requires --server, --status and --detail")
        _print(bridge.registry.note_health(args.server, args.status, args.detail))
        return 0
    if args.action == "describe":
        if not args.server or not args.tool:
            raise ValidationFailed("catalog describe requires --server and --tool")
        _print(bridge.registry.contract(args.server, args.tool))
        return 0
    if args.action == "accept":
        if not args.server:
            print("--server is required", file=sys.stderr)
            return 2
        n = bridge.registry.accept(args.server, args.tool)
        print(f"accepted {n} changed tool(s)")
        return 0
    inv = bridge.registry.inventory()
    if args.action == "status":
        _print({"catalog": bridge.registry.catalog_status(), "servers": [{k: s[k] for k in ("server", "status", "tool_count", "protocol_version", "consecutive_failures")} for s in inv["servers"]]})
        return 0
    clauses, params = ["status!='OK'"], []
    if args.server:
        clauses.append("server=?")
        params.append(args.server)
    if args.tool:
        clauses.append("tool=?")
        params.append(args.tool)
    where = " AND ".join(clauses)
    if not 1 <= args.limit <= 200 or args.offset < 0:
        raise ValidationFailed("catalog pagination needs limit 1..200 and nonnegative offset")
    with bridge.store.read() as con:
        total = con.execute(f"SELECT COUNT(*) FROM providers WHERE {where}", params).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"SELECT server,tool,status,substr(schema_digest,1,12) schema FROM providers WHERE {where} ORDER BY server,tool LIMIT ? OFFSET ?", [*params, args.limit, args.offset])]
    _print({"tools": rows, "total": total, "offset": args.offset, "has_more": args.offset + len(rows) < total})
    return 0


def cmd_status(args) -> int:
    bridge = build()
    with bridge.store.read() as con:
        wf = [dict(r) for r in con.execute("SELECT domain,state,COUNT(*) n FROM workflows GROUP BY domain,state")]
        pend = [dict(r) for r in con.execute("SELECT id,workflow_id,target,expires_at FROM approvals WHERE state IN ('PENDING','GRANTED')")]
        unresolved = [dict(r) for r in con.execute("SELECT id,workflow_id,state,target FROM executions WHERE state IN ('STARTED','OUTCOME_UNKNOWN')")]
    _print({
        "version": __version__, "home": str(bridge.settings.home), "integrity": bridge.store.integrity(), "workflows": wf,
        "open_approvals": pend, "unresolved_executions": unresolved, "catalog": bridge.registry.catalog_status(),
        "approver": bridge.approvals.key_health(),
    })
    return 0


def cmd_workflows(args) -> int:
    bridge = build()
    if args.id:
        wf = bridge.engine.get(args.id)
        _print(wf)
        return 0
    _print(bridge.engine.list(args.domain, [args.state] if args.state else None, args.limit))
    return 0


def cmd_logs(args) -> int:
    bridge = build()
    log = bridge.settings.logs_dir / "bridge.log"
    if not log.exists():
        print("no log file yet")
        return 0
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-args.tail :]))
    return 0


def cmd_integrity(args) -> int:
    bridge = build()
    out = bridge.store.integrity()
    _print(out)
    return 0 if out["ok"] else 1


def cmd_backup(args) -> int:
    bridge = build()
    if getattr(args, "full", False):
        from .backup import create_full_backup
        dest = Path(args.out) if args.out else bridge.settings.backups_dir / f"bridge-full-{time.time_ns()}.zip"
        _print(create_full_backup(bridge, dest, max_bytes=args.max_bytes))
        return 0
    dest = Path(args.out) if args.out else bridge.settings.backups_dir / f"bridge-{datetime.now().strftime('%Y%m%dT%H%M%S')}.db"
    bridge.store.backup(dest)
    check = sqlite3.connect(dest)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    print(f"backup written: {dest} (integrity: {ok})")
    return 0 if ok == "ok" else 1


def cmd_restore(args) -> int:
    if getattr(args, "into", None):
        from .backup import restore_full_backup
        _print(restore_full_backup(Path(args.source), Path(args.into), max_bytes=args.max_bytes))
        return 0
    bridge = build()
    src = Path(args.source)
    if not src.is_file() or src.resolve() == bridge.settings.db_path.resolve():
        raise ValidationFailed("restore source must be an existing backup file different from the live database")
    if zipfile.is_zipfile(src):
        raise ValidationFailed("full snapshots require --into with a new restore directory")
    if Path(str(src) + "-wal").exists():
        raise ValidationFailed("source has a WAL; create a consistent database backup first")
    check = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            print("backup failed its integrity check", file=sys.stderr)
            return 1
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"schema_migrations", "workflows", "artifacts", "approvals"} <= tables:
            raise ValidationFailed("restore source is not an XN-Bridge backup")
        version = check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if not isinstance(version, int) or version > bridge.store.schema_version:
            raise ValidationFailed("backup schema is newer than this runtime")
        if check.execute("PRAGMA foreign_key_check").fetchone():
            raise ValidationFailed("backup has foreign key violations")
    except sqlite3.Error as e:
        raise ValidationFailed("restore source is not a valid SQLite snapshot") from e
    finally:
        check.close()
    from .backup import file_digest, invalidate_restored_approvals
    with tempfile.TemporaryDirectory(dir=bridge.settings.home, prefix=".restore-") as tmp:
        candidate = Path(tmp) / "bridge.db"
        shutil.copy2(src, candidate)
        candidate.chmod(0o600)
        revoked, uncertain = invalidate_restored_approvals(candidate, file_digest(src))
        live = bridge.settings.db_path
        aside = live.with_suffix(f".before-restore-{time.time_ns()}")
        moved = []
        try:
            for suffix in ("", "-wal", "-shm"):
                old = Path(str(live) + suffix)
                if old.exists():
                    saved = Path(str(aside) + suffix)
                    os.replace(old, saved)
                    moved.append((old, saved))
            os.replace(candidate, live)
        except OSError:
            for old, saved in reversed(moved):
                os.replace(saved, old)
            raise
    print(f"restored {src} -> {live}; previous database kept at {aside}; revoked approvals={revoked}, uncertain external attempts={uncertain}")
    return 0


def cmd_verify_backup(args) -> int:
    from .backup import verify_full_backup
    _print(verify_full_backup(Path(args.source), max_bytes=args.max_bytes))
    return 0


def mcp_entry() -> dict[str, Any]:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        command, args = str(venv_python), ["-m", "xnbridge.server"]
    else:
        command, args = shutil.which("uv") or "uv", ["run", "--directory", str(REPO_ROOT), "--quiet", "python", "-m", "xnbridge.server"]
    return {"command": command, "args": args, "env": {"XN_BRIDGE_HOME": str(REPO_ROOT / "data")}}


def cmd_register(args) -> int:
    if args.host == "codex":
        target = Path(args.file) if args.file else codex_config()
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        entry = mcp_entry()
        entry["env"]["XN_BRIDGE_HOST"] = "codex"
        if not os.access(entry["command"], os.X_OK):
            raise BridgeError("bridge executable is unavailable")
        text = codex_registration(old, entry)
        if text == old:
            _print({"status": "already_registered", "file": str(target)})
            return 0
        if not args.write:
            _print({"file": str(target), "addition": entry, "status": "dry_run"})
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = target.with_name(target.name + f".xnb-backup-{time.time_ns()}")
        if target.exists():
            shutil.copy2(target, backup)
            backup.chmod(0o600)
        target.write_text(text, encoding="utf-8")
        target.chmod(0o600)
        import tomllib
        tomllib.loads(target.read_text())
        _print({"status": "registered", "file": str(target), "backup": str(backup) if backup.exists() else None,
                "rollback": "stop bridge sessions, then restore the backup file", "preserved_existing_entries": True})
        return 0
    target = Path(args.file) if args.file else REPO_ROOT / ".mcp.json"
    entry = mcp_entry()
    if not Path(entry["command"]).is_absolute() or not os.access(entry["command"], os.X_OK):
        print(f"executable not found or not absolute: {entry['command']}", file=sys.stderr)
        return 1
    data: dict[str, Any] = {"mcpServers": {}}
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        data.setdefault("mcpServers", {})
    merged = {**data, "mcpServers": {**data["mcpServers"], "xn-bridge": entry}}
    if not args.write:
        _print({"file": str(target), "addition": {"xn-bridge": entry}, "preserved_existing_servers": sorted(k for k in merged["mcpServers"] if k != "xn-bridge")})
        print("\n(dry run: nothing written; add --write to apply)", file=sys.stderr)
        return 0
    if target.exists():
        backup = target.with_name(target.name + f".bak-{int(time.time())}")
        shutil.copy2(target, backup)
        print(f"backup: {backup}")
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    json.loads(target.read_text(encoding="utf-8"))
    print(f"registered xn-bridge in {target}; other entries preserved: {sorted(k for k in merged['mcpServers'] if k != 'xn-bridge')}")
    print("rollback: restore the .bak file, or delete the xn-bridge key; the host asks for approval of project servers")
    return 0


def _ollama_models(url: str) -> list[str] | None:
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return None


def cmd_doctor(args) -> int:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    add("python", "PASS" if sys.version_info >= (3, 14) else "FAIL", sys.version.split()[0])
    try:
        import importlib.metadata as md

        add("mcp sdk", "PASS", md.version("mcp"))
    except Exception as e:
        add("mcp sdk", "FAIL", str(e))
    bridge = build()
    add("sqlite", "PASS", sqlite3.sqlite_version)
    integ = bridge.store.integrity()
    add("database integrity", "PASS" if integ["ok"] else "FAIL", f"journal={integ['journal_mode']} schema={integ['schema_version']}")
    mode = oct(bridge.settings.home.stat().st_mode & 0o777)
    add("data dir permissions", "PASS" if mode == "0o700" else "WARN", f"{bridge.settings.home} {mode}")
    k = bridge.approvals.key_health()
    add("approver key", "PASS" if k["configured"] and k["private_key_mode_ok"] else "WARN", f"fingerprint={k['fingerprint']}; run `xnbridge approval-init` if missing")
    entry = mcp_entry()
    add("launch command", "PASS" if os.access(entry["command"], os.X_OK) else "FAIL", entry["command"])
    proj = codex_config() if primary_host() == "codex" else REPO_ROOT / ".mcp.json"
    if proj.exists():
        if primary_host() == "codex":
            import tomllib
            registered = tomllib.loads(proj.read_text()).get("mcp_servers", {})
        else:
            registered = json.loads(proj.read_text()).get("mcpServers", {})
        add("host registration", "PASS" if "xn-bridge" in registered else "WARN", str(proj))
    else:
        add("project registration", "WARN", "run `xnbridge register --write`")
    cat = bridge.registry.catalog_status()
    add("capability catalog", "WARN" if cat["stale"] else "PASS", f"age_s={cat['age_s']} servers={cat['servers']}")
    quarantined = cat["tools"].get("CHANGED", 0)
    add("quarantined schemas", "WARN" if quarantined else "PASS", f"{quarantined}; review changed contracts with `xnbridge catalog changed` before accepting them")
    models = _ollama_models(bridge.settings.policy["routing"]["l1_url"])
    add("local model runner (optional)", "PASS" if models is not None else "WARN", f"models={models}" if models is not None else "ollama not reachable on loopback")
    add("memory", "PASS", f"rss={self_rss_mb()}MB mem_available={mem_available_mb()}MB")
    add("network mode", "PASS", "offline" if bridge.settings.policy["network"]["offline"] else "online (public internet allowed for search/ATS only; no listener)")
    _print({"checks": checks, "failed": sum(c["status"] == "FAIL" for c in checks), "warnings": sum(c["status"] == "WARN" for c in checks)})
    return 1 if any(c["status"] == "FAIL" for c in checks) else 0


def cmd_dry_run(args) -> int:
    from .dryrun import run_career, run_research

    if args.domain == "career":
        out = run_career(simulate=args.simulate, keep=args.keep)
    else:
        out = run_research()
    _print(out)
    return 0 if out.get("all_checks_passed") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xnbridge", description="XN-Bridge local coordination layer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="validate dependencies, config and local state").set_defaults(fn=cmd_doctor)
    sub.add_parser("status", help="state summary").set_defaults(fn=cmd_status)
    sub.add_parser("integrity", help="database integrity check").set_defaults(fn=cmd_integrity)
    d = sub.add_parser("discover", help="audit configured MCP servers (read-only)")
    d.add_argument("--host", choices=["codex", "claude"], default=primary_host())
    d.add_argument("--config", help="explicit host configuration path")
    d.add_argument("--via-host", action="store_true", help="use Codex-owned inventory connections instead of direct MCP audit clients")
    d.add_argument("--watch-seconds", type=float, default=0, help="bounded targeted refresh; requires --via-host and --only")
    d.add_argument("--poll-interval", type=float, default=2)
    d.add_argument("--only", nargs="*")
    d.add_argument("--probe-http", action="store_true")
    d.add_argument("--timeout", type=float, default=75.0)
    d.add_argument("--out")
    d.add_argument("--project-mcp")
    d.set_defaults(fn=cmd_discover)
    c = sub.add_parser("catalog", help="inspect or accept changed tool schemas")
    c.add_argument("action", choices=["status", "changed", "describe", "accept", "health"], nargs="?", default="status")
    c.add_argument("--server")
    c.add_argument("--tool")
    c.add_argument("--limit", type=int, default=50)
    c.add_argument("--offset", type=int, default=0)
    c.add_argument("--status", choices=["OK", "AUTH_REQUIRED", "PERMISSION_DENIED", "FAILED", "STALE"])
    c.add_argument("--detail", help="operator observation, without credentials")
    c.set_defaults(fn=cmd_catalog)
    sub.add_parser("approval-init", help="create the passphrase-protected approver key (human, interactive)").set_defaults(fn=cmd_approval_init)
    a = sub.add_parser("approve", help="human approval of one prepared payload (interactive)")
    a.add_argument("approval_id")
    a.set_defaults(fn=cmd_approve)
    ap = sub.add_parser("approvals", help="list approvals")
    ap.add_argument("--limit", type=int, default=20)
    ap.set_defaults(fn=cmd_approvals)
    w = sub.add_parser("workflows", help="list or show workflows")
    w.add_argument("id", nargs="?")
    w.add_argument("--domain")
    w.add_argument("--state")
    w.add_argument("--limit", type=int, default=20)
    w.set_defaults(fn=cmd_workflows)
    lg = sub.add_parser("logs", help="tail the bridge log")
    lg.add_argument("--tail", type=int, default=40)
    lg.set_defaults(fn=cmd_logs)
    b = sub.add_parser("backup", help="consistent online backup of the database")
    b.add_argument("--out")
    b.add_argument("--full", action="store_true", help="include referenced artifacts, local config and encrypted approval keys")
    b.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    b.set_defaults(fn=cmd_backup)
    r = sub.add_parser("restore", help="restore a backup (previous database is kept)")
    r.add_argument("source")
    r.add_argument("--into", help="restore a full-state ZIP into a new directory, preserving current state")
    r.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    r.set_defaults(fn=cmd_restore)
    vb = sub.add_parser("verify-backup", help="validate every full-state snapshot digest and database reference")
    vb.add_argument("source")
    vb.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    vb.set_defaults(fn=cmd_verify_backup)
    rg = sub.add_parser("register", help="add xn-bridge to the project-scope .mcp.json (backup first, other entries preserved)")
    rg.add_argument("--host", choices=["codex", "claude"], default=primary_host())
    rg.add_argument("--file")
    rg.add_argument("--write", action="store_true")
    rg.set_defaults(fn=cmd_register)
    dr = sub.add_parser("dry-run", help="end-to-end fixture workflow in an isolated temporary home; sends nothing")
    dr.add_argument("domain", choices=["career", "research"])
    dr.add_argument("--simulate", choices=["success", "timeout"], default="success")
    dr.add_argument("--keep", action="store_true")
    dr.set_defaults(fn=cmd_dry_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except BridgeError as e:
        print(json.dumps(e.as_dict(), indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
