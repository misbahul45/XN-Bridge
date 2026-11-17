"""Private full-state snapshots using SQLite backup and bounded, verified ZIP files.

Restore publishes only a new directory. It never replaces a live bridge home.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ValidationFailed
from .store import MIGRATIONS, now_iso

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 10000
MAX_MANIFEST = 2 * 1024 * 1024
CHUNK = 128 * 1024
KEYS = {"approver.pub", "approver.key.enc"}


def _path(name: str) -> str:
    p = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or "\x00" in name or p.is_absolute()
            or any(x in (".", "..", "") for x in name.split("/")) or p.as_posix() != name):
        raise ValidationFailed("snapshot contains an unsafe path")
    if name in {"bridge.db", *KEYS} or (len(p.parts) >= 2 and p.parts[0] in ("artifacts", "config")):
        return name
    raise ValidationFailed("snapshot contains an unsupported state file")


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _db(root: Path) -> tuple[int, dict[str, tuple[str, int]]]:
    try:
        with closing(sqlite3.connect((root / "bridge.db").as_uri() + "?mode=ro", uri=True)) as con:
            if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or con.execute("PRAGMA foreign_key_check").fetchone():
                raise ValidationFailed("snapshot database failed integrity validation")
            versions = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
            known = {v for v, _ in MIGRATIONS}
            if not versions or not versions <= known or 1 not in versions:
                raise ValidationFailed("snapshot database has an unsupported schema")
            required = {"workflows", "steps", "approvals", "executions", "evidence", "artifacts", "audit", "catalog_meta"}
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables:
                raise ValidationFailed("snapshot is missing bridge tables")
            artifacts = {}
            for rel, digest, size in con.execute("SELECT rel_path,digest,bytes FROM artifacts"):
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or rel != f"{digest[:2]}/{digest}":
                    raise ValidationFailed("snapshot database contains an invalid artifact path")
                name = "artifacts/" + rel
                if name in artifacts and artifacts[name] != (digest, size):
                    raise ValidationFailed("snapshot has conflicting artifact records")
                artifacts[name] = (digest, size)
            return max(versions), artifacts
    except sqlite3.Error as e:
        raise ValidationFailed("snapshot is not a valid bridge database") from e


def _source(root: Path, relative: str) -> Path:
    p = root
    for part in PurePosixPath(relative).parts:
        p = p / part
        if p.is_symlink():
            raise ValidationFailed("snapshot source must not contain symlinks")
    if not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise ValidationFailed("a required snapshot source file is missing")
    return p


def create_full_backup(bridge: Any, destination: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValidationFailed("full backup destination must be a new file")
    for directory in (bridge.settings.config_dir, bridge.settings.artifacts_dir):
        if destination.resolve().is_relative_to(directory.resolve()):
            raise ValidationFailed("backup cannot be stored inside artifact or config inputs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xnbridge-snapshot-") as tmp:
        scratch = Path(tmp)
        bridge.store.backup(scratch / "bridge.db")
        version, artifacts = _db(scratch)
        files = {"bridge.db": scratch / "bridge.db"}
        files.update({name: _source(bridge.settings.home, name) for name in artifacts})
        for p in bridge.settings.config_dir.rglob("*"):
            if p.is_symlink():
                raise ValidationFailed("snapshot config must not contain symlinks")
            if p.is_file():
                name = _path(p.relative_to(bridge.settings.home).as_posix())
                files[name] = _source(bridge.settings.home, name)
        present_keys = {name for name in KEYS if (bridge.settings.home / name).exists() or (bridge.settings.home / name).is_symlink()}
        if present_keys and present_keys != KEYS:
            raise ValidationFailed("approver key pair is incomplete")
        files.update({name: _source(bridge.settings.home, name) for name in present_keys})
        if len(files) > MAX_FILES:
            raise ValidationFailed("snapshot file count exceeds the limit")
        manifest = {"format": "xn-bridge-full-state", "version": 1, "created_at": now_iso(), "schema_version": version, "files": {}}
        total = 0
        # Same-directory temporary output allows no-overwrite atomic publication.
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".xnbridge-backup-") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as out:
                for name, source in sorted(files.items()):
                    digest = hashlib.sha256()
                    count = 0
                    with source.open("rb") as src, out.open(name, "w", force_zip64=True) as target:
                        for block in iter(lambda: src.read(CHUNK), b""):
                            count += len(block)
                            total += len(block)
                            if total > max_bytes:
                                raise ValidationFailed("snapshot exceeds max_bytes")
                            digest.update(block)
                            target.write(block)
                    hexdigest = digest.hexdigest()
                    if name in artifacts and artifacts[name] != (hexdigest, count):
                        raise ValidationFailed("artifact digest or size differs from its database record")
                    manifest["files"][name] = {"sha256": hexdigest, "bytes": count}
                raw = json.dumps(manifest, sort_keys=True).encode()
                if len(raw) > MAX_MANIFEST:
                    raise ValidationFailed("snapshot manifest exceeds the limit")
                out.writestr("manifest.json", raw)
            handle.flush()
            os.fsync(handle.fileno())
            try:
                os.link(handle.name, destination)
            except FileExistsError as e:
                raise ValidationFailed("full backup destination already exists") from e
    return {"ok": True, "path": str(destination), "files": len(files), "artifacts": len(artifacts), "bytes": total,
            "sha256": file_digest(destination), "schema_version": version}


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationFailed("snapshot manifest has duplicate keys")
        result[key] = value
    return result


def _unpack(source: Path, root: Path, max_bytes: int) -> dict:
    try:
        with zipfile.ZipFile(source) as archive:
            items = archive.infolist()
            names = [i.filename for i in items]
            if len(items) > MAX_FILES + 1 or len(names) != len(set(names)) or "manifest.json" not in names:
                raise ValidationFailed("snapshot has duplicate, missing or excessive entries")
            total = 0
            for info in items:
                if info.filename != "manifest.json":
                    _path(info.filename)
                    total += info.file_size
                if (info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValidationFailed("snapshot entry type is unsupported")
            if total > max_bytes or archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
                raise ValidationFailed("snapshot exceeds configured size limits")
            manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_unique_json)
            if (not isinstance(manifest, dict) or manifest.get("format") != "xn-bridge-full-state" or manifest.get("version") != 1
                    or not isinstance(manifest.get("files"), dict) or "bridge.db" not in manifest["files"]):
                raise ValidationFailed("invalid full-state manifest")
            if set(manifest["files"]) != set(names) - {"manifest.json"}:
                raise ValidationFailed("snapshot entries differ from the manifest")
            for name, meta in manifest["files"].items():
                _path(name)
                if (not isinstance(meta, dict) or type(meta.get("bytes")) is not int or meta["bytes"] < 0
                        or not isinstance(meta.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"])):
                    raise ValidationFailed("invalid snapshot file metadata")
                if archive.getinfo(name).file_size != meta["bytes"]:
                    raise ValidationFailed("snapshot file length differs from manifest")
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                h = hashlib.sha256()
                count = 0
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as out, archive.open(name) as src:
                    for block in iter(lambda: src.read(CHUNK), b""):
                        count += len(block)
                        if count > meta["bytes"]:
                            raise ValidationFailed("snapshot entry exceeds its declared size")
                        h.update(block)
                        out.write(block)
                if count != meta["bytes"] or h.hexdigest() != meta["sha256"]:
                    raise ValidationFailed("snapshot digest validation failed")
            version, artifacts = _db(root)
            if version != manifest.get("schema_version"):
                raise ValidationFailed("snapshot schema differs from the manifest")
            if {n for n in names if n.startswith("artifacts/")} != set(artifacts):
                raise ValidationFailed("snapshot artifacts differ from database references")
            for name, (digest, size) in artifacts.items():
                if manifest["files"][name] != {"sha256": digest, "bytes": size}:
                    raise ValidationFailed("snapshot artifact digest differs from the database")
            keys = KEYS & set(names)
            if keys and keys != KEYS:
                raise ValidationFailed("snapshot approver key pair is incomplete")
            return manifest
    except (zipfile.BadZipFile, OSError, ValueError, TypeError, KeyError) as e:
        raise ValidationFailed("invalid or damaged full-state snapshot") from e


def invalidate_restored_approvals(database: Path, source_digest: str) -> tuple[int, int]:
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("PRAGMA foreign_keys=ON")
        revoked = con.execute("UPDATE approvals SET state='REVOKED' WHERE state IN ('PENDING','GRANTED')").rowcount
        uncertain = con.execute("UPDATE executions SET state='OUTCOME_UNKNOWN',error_class='UNKNOWN_SIDE_EFFECT',finished_at=? WHERE risk='EXTERNAL_WRITE' AND state='STARTED'", (now_iso(),)).rowcount
        con.execute("UPDATE workflows SET state='RECONCILIATION_REQUIRED',updated_at=? WHERE id IN (SELECT workflow_id FROM executions WHERE risk='EXTERNAL_WRITE' AND state='OUTCOME_UNKNOWN')", (now_iso(),))
        con.execute("UPDATE workflows SET state='BLOCKED',updated_at=? WHERE state='AWAITING_APPROVAL'", (now_iso(),))
        con.execute("INSERT INTO audit(ts,actor,kind,detail_json) VALUES (?,?,?,?)", (now_iso(), "local-cli", "state_restored", json.dumps({"source_sha256": source_digest, "revoked_approvals": revoked, "uncertain_executions": uncertain})))
    return revoked, uncertain


def restore_full_backup(source: Path, destination: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if not source.is_file() or destination.exists() or destination.is_symlink():
        raise ValidationFailed("restore requires an existing archive and a new destination directory")
    if source.stat().st_size > max_bytes + 8 * 1024 * 1024:
        raise ValidationFailed("snapshot archive exceeds configured size limits")
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive_digest = file_digest(source)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".xnbridge-restore-") as tmp:
        root = Path(tmp) / "state"
        root.mkdir(mode=0o700)
        manifest = _unpack(source, root, max_bytes)
        revoked, uncertain = invalidate_restored_approvals(root / "bridge.db", archive_digest)
        _db(root)
        try:
            destination.mkdir(mode=0o700)
        except FileExistsError as e:
            raise ValidationFailed("restore destination appeared during validation") from e
        try:
            os.replace(root, destination)
        except OSError:
            # Remove only our empty reservation, never recursively remove user state.
            try:
                destination.rmdir()
            except OSError:
                pass
            raise
    return {"ok": True, "home": str(destination), "integrity": "ok", "files": len(manifest["files"]),
            "revoked_approvals": revoked, "uncertain_executions": uncertain,
            "next": "use XN_BRIDGE_HOME for the restored directory; review external outcomes before granting new approvals"}


def verify_full_backup(source: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    source = Path(source).absolute()
    if not source.is_file() or source.stat().st_size > max_bytes + 8 * 1024 * 1024:
        raise ValidationFailed("snapshot file is missing or exceeds size limits")
    with tempfile.TemporaryDirectory(prefix="xnbridge-verify-") as tmp:
        manifest = _unpack(source, Path(tmp), max_bytes)
    return {"ok": True, "integrity": "ok", "files": len(manifest["files"]), "schema_version": manifest["schema_version"],
            "bytes": sum(f["bytes"] for f in manifest["files"].values()), "sha256": file_digest(source)}
