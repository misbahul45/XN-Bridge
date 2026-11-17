from __future__ import annotations

from typing import Any, Callable

from .errors import NotFound
from .store import jdump, jload, new_id, now_iso


def _row(r) -> dict[str, Any]:
    return {
        "id": r["id"],
        "workflow_id": r["workflow_id"],
        "kind": r["kind"],
        "dedupe_key": r["dedupe_key"],
        "status": r["status"],
        "data": jload(r["data_json"], {}),
        "version": r["version"],
    }


def find(con, workflow_id: str, kind: str, dedupe_key: str) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM entities WHERE workflow_id=? AND kind=? AND dedupe_key=?", (workflow_id, kind, dedupe_key)).fetchone()
    return _row(r) if r else None


def get(con, entity_id: str, workflow_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
    q = "SELECT * FROM entities WHERE id=?"
    args: list[Any] = [entity_id]
    if workflow_id:
        q += " AND workflow_id=?"
        args.append(workflow_id)
    if kind:
        q += " AND kind=?"
        args.append(kind)
    r = con.execute(q, args).fetchone()
    if r is None:
        raise NotFound(f"{kind or 'entity'} '{entity_id}' not found in this workflow")
    return _row(r)


def listing(con, workflow_id: str, kind: str, status: str | list[str] | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    q = "SELECT * FROM entities WHERE workflow_id=? AND kind=?"
    args: list[Any] = [workflow_id, kind]
    if status:
        sts = [status] if isinstance(status, str) else list(status)
        q += f" AND status IN ({','.join('?' * len(sts))})"
        args += sts
    q += " ORDER BY created_at, id LIMIT ?"
    args.append(limit)
    return [_row(r) for r in con.execute(q, args)]


def upsert(
    con,
    workflow_id: str,
    kind: str,
    dedupe_key: str,
    data: dict[str, Any],
    status: str | None = None,
    merge: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    existing = find(con, workflow_id, kind, dedupe_key)
    ts = now_iso()
    if existing is None:
        eid = new_id(kind[:4])
        con.execute(
            "INSERT INTO entities(id,workflow_id,kind,dedupe_key,status,data_json,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, workflow_id, kind, dedupe_key, status, jdump(data), 1, ts, ts),
        )
        return {"id": eid, "workflow_id": workflow_id, "kind": kind, "dedupe_key": dedupe_key, "status": status, "data": data, "version": 1}, True
    merged = merge(existing["data"], data) if merge else data
    new_status = status if status is not None else existing["status"]
    con.execute(
        "UPDATE entities SET data_json=?, status=?, version=version+1, updated_at=? WHERE id=?",
        (jdump(merged), new_status, ts, existing["id"]),
    )
    return {**existing, "data": merged, "status": new_status, "version": existing["version"] + 1}, False


def update(con, entity_id: str, data: dict[str, Any], status: str | None = None) -> None:
    if status is not None:
        con.execute("UPDATE entities SET data_json=?, status=?, version=version+1, updated_at=? WHERE id=?", (jdump(data), status, now_iso(), entity_id))
    else:
        con.execute("UPDATE entities SET data_json=?, version=version+1, updated_at=? WHERE id=?", (jdump(data), now_iso(), entity_id))


def counts(con, workflow_id: str) -> dict[str, int]:
    return {r["kind"]: r["n"] for r in con.execute("SELECT kind,COUNT(*) n FROM entities WHERE workflow_id=? GROUP BY kind", (workflow_id,))}
