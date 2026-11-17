from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import LimitExceeded, NotFound
from .security import digest_bytes, safe_join
from .store import Store, new_id, now_iso

DEFAULT_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class ArtifactStore:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def put(
        self,
        workflow_id: str | None,
        kind: str,
        content: bytes | str,
        mime: str = "application/octet-stream",
        *,
        max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        con=None,
    ) -> dict[str, Any]:
        data = content.encode("utf-8") if isinstance(content, str) else content
        if len(data) > max_bytes:
            raise LimitExceeded(f"artifact of {len(data)} bytes exceeds limit {max_bytes}")
        digest = digest_bytes(data)
        rel = Path(digest[:2]) / digest
        dest = safe_join(self.settings.artifacts_dir, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            tmp = dest.with_suffix(f".tmp{os.getpid()}")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        aid = new_id("art")
        row = (aid, workflow_id, kind, rel.as_posix(), digest, len(data), mime, now_iso())
        sql = "INSERT INTO artifacts(id,workflow_id,kind,rel_path,digest,bytes,mime,created_at) VALUES (?,?,?,?,?,?,?,?)"
        if con is not None:
            con.execute(sql, row)
        else:
            with self.store.tx() as c:
                c.execute(sql, row)
        return {"id": aid, "digest": digest, "bytes": len(data), "kind": kind, "mime": mime}

    def meta(self, artifact_id: str) -> dict[str, Any]:
        with self.store.read() as con:
            r = con.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if r is None:
            raise NotFound(f"artifact '{artifact_id}' not found")
        return dict(r)

    def read(self, artifact_id: str, max_bytes: int | None = None) -> tuple[dict[str, Any], bytes]:
        meta = self.meta(artifact_id)
        path = safe_join(self.settings.artifacts_dir, meta["rel_path"])
        if not path.is_file():
            raise NotFound(f"artifact file for '{artifact_id}' is missing on disk")
        data = path.read_bytes()
        if digest_bytes(data) != meta["digest"]:
            raise NotFound(f"artifact '{artifact_id}' failed digest verification")
        if max_bytes is not None and len(data) > max_bytes:
            data = data[:max_bytes]
            meta = {**meta, "truncated": True}
        return meta, data

    def read_text(self, artifact_id: str, max_bytes: int | None = None) -> str:
        _, data = self.read(artifact_id, max_bytes)
        return data.decode("utf-8", errors="replace")
