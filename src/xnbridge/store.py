from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .errors import ValidationFailed

BUSY_TIMEOUT_MS = 8000

MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """CREATE TABLE workflows (
  id TEXT PRIMARY KEY,
  domain TEXT NOT NULL,
  title TEXT,
  state TEXT NOT NULL CHECK (state IN ('CREATED','PLANNED','RUNNING','PAUSED','BLOCKED',
    'AWAITING_APPROVAL','RECONCILIATION_REQUIRED','COMPLETED','FAILED','CANCELLED')),
  stage TEXT,
  spec_version INTEGER NOT NULL DEFAULT 1,
  params_json TEXT NOT NULL DEFAULT '{}',
  counters_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deadline_at TEXT
)""",
            """CREATE TABLE steps (
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  ord INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
    ('PENDING','RUNNING','DONE','SKIPPED','FAILED','BLOCKED')),
  attempts INTEGER NOT NULL DEFAULT 0,
  started_at TEXT, finished_at TEXT, output_json TEXT,
  PRIMARY KEY (workflow_id, name)
)""",
            """CREATE TABLE workflow_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  from_state TEXT, to_state TEXT,
  detail_json TEXT,
  idempotency_key TEXT
)""",
            """CREATE UNIQUE INDEX idx_events_idem ON workflow_events(workflow_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL""",
            "CREATE INDEX idx_events_wf ON workflow_events(workflow_id, id)",
            """CREATE TABLE checkpoints (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  stage TEXT, state TEXT NOT NULL,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (workflow_id, seq)
)""",
            """CREATE TABLE entities (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  status TEXT,
  data_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (workflow_id, kind, dedupe_key)
)""",
            """CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  workflow_id TEXT REFERENCES workflows(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  digest TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  mime TEXT,
  created_at TEXT NOT NULL
)""",
            "CREATE INDEX idx_artifacts_digest ON artifacts(digest)",
            """CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  workflow_id TEXT REFERENCES workflows(id) ON DELETE CASCADE,
  claim TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('tool_output','local_file','user_statement','model_summary')),
  source_id TEXT, source_ref TEXT,
  provider TEXT,
  retrieved_at TEXT NOT NULL,
  verification TEXT NOT NULL CHECK (verification IN ('VERIFIED','UNVERIFIED','INFERRED','UNKNOWN')),
  uncertainty TEXT,
  digest TEXT,
  artifact_id TEXT REFERENCES artifacts(id),
  excerpt TEXT,
  ttl_class TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL
)""",
            "CREATE INDEX idx_evidence_wf ON evidence(workflow_id)",
            """CREATE TABLE approvals (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  action_kind TEXT NOT NULL,
  target TEXT NOT NULL,
  target_origin TEXT NOT NULL,
  payload_ref TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PENDING','GRANTED','CONSUMED','EXPIRED','REVOKED','REJECTED')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  granted_at TEXT,
  signature TEXT,
  consumed_at TEXT,
  consumed_by TEXT
)""",
            """CREATE TABLE executions (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  capability TEXT NOT NULL,
  provider TEXT, tool TEXT,
  risk TEXT NOT NULL CHECK (risk IN ('READ','LOCAL_WRITE','EXTERNAL_WRITE')),
  idempotency_key TEXT NOT NULL,
  dedupe_key TEXT,
  state TEXT NOT NULL CHECK (state IN ('STARTED','SUCCEEDED','FAILED','OUTCOME_UNKNOWN',
    'RECONCILED_SUCCEEDED','RECONCILED_FAILED')),
  approval_id TEXT REFERENCES approvals(id),
  payload_digest TEXT, target TEXT,
  error_class TEXT,
  started_at TEXT NOT NULL, finished_at TEXT, latency_ms INTEGER,
  detail_json TEXT,
  UNIQUE (workflow_id, idempotency_key)
)""",
            """CREATE UNIQUE INDEX idx_exec_external_once ON executions(dedupe_key)
  WHERE risk = 'EXTERNAL_WRITE' AND dedupe_key IS NOT NULL
    AND state IN ('STARTED','SUCCEEDED','OUTCOME_UNKNOWN','RECONCILED_SUCCEEDED')""",
            """CREATE TABLE providers (
  server TEXT NOT NULL,
  tool TEXT NOT NULL,
  schema_digest TEXT NOT NULL,
  desc_digest TEXT NOT NULL,
  accepted_schema_digest TEXT,
  accepted_desc_digest TEXT,
  status TEXT NOT NULL CHECK (status IN ('OK','CHANGED','UNAVAILABLE')),
  protocol_version TEXT,
  server_version TEXT,
  has_output_schema INTEGER NOT NULL DEFAULT 0,
  summary TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (server, tool)
)""",
            """CREATE TABLE server_health (
  server TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  detail TEXT,
  protocol_version TEXT,
  tool_count INTEGER NOT NULL DEFAULT 0,
  transport TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  cooldown_until TEXT,
  last_checked_at TEXT NOT NULL,
  last_ok_at TEXT
)""",
            "CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            """CREATE TABLE metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  workflow_id TEXT,
  name TEXT NOT NULL,
  value REAL NOT NULL,
  detail_json TEXT
)""",
            """CREATE TABLE audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail_json TEXT
)""",
        ],
    ),
]


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def jdump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def jload(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    return json.loads(s)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
        finally:
            con.close()

    def _migrate(self) -> None:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            have = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
            for version, statements in MIGRATIONS:
                if version in have:
                    continue
                for stmt in statements:
                    con.execute(stmt)
                con.execute("INSERT INTO schema_migrations VALUES (?,?)", (version, now_iso()))
            con.execute("COMMIT")
        except BaseException:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    @property
    def schema_version(self) -> int:
        with self.read() as con:
            return con.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]

    def integrity(self) -> dict[str, Any]:
        with self.read() as con:
            ic = con.execute("PRAGMA integrity_check").fetchall()
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            jm = con.execute("PRAGMA journal_mode").fetchone()[0]
        rows = [r[0] for r in ic]
        return {
            "integrity": rows,
            "ok": rows == ["ok"] and not fk,
            "foreign_key_violations": len(fk),
            "journal_mode": jm,
            "schema_version": self.schema_version,
        }

    def backup(self, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == self.path.resolve() or dest.exists() or dest.is_symlink():
            raise ValidationFailed("backup destination must be a new file different from the live database")
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        src = self._connect()
        try:
            out = sqlite3.connect(dest)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
        return dest

    def audit(self, con: sqlite3.Connection, actor: str, kind: str, detail: Any = None) -> None:
        con.execute(
            "INSERT INTO audit(ts,actor,kind,detail_json) VALUES (?,?,?,?)",
            (now_iso(), actor, kind, jdump(detail)),
        )

    def metric_tx(self, con: sqlite3.Connection, name: str, value: float, workflow_id: str | None = None, detail: Any = None) -> None:
        con.execute(
            "INSERT INTO metrics(ts,workflow_id,name,value,detail_json) VALUES (?,?,?,?,?)",
            (now_iso(), workflow_id, name, float(value), jdump(detail) if detail is not None else None),
        )

    def metric(self, name: str, value: float, workflow_id: str | None = None, detail: Any = None) -> None:
        with self.tx() as con:
            con.execute(
                "INSERT INTO metrics(ts,workflow_id,name,value,detail_json) VALUES (?,?,?,?,?)",
                (now_iso(), workflow_id, name, float(value), jdump(detail) if detail is not None else None),
            )


def retry_busy(fn, attempts: int = 5, delay: float = 0.05):
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                raise
            if i == attempts - 1:
                raise
            time.sleep(delay * (2**i))
