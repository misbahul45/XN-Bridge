from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .artifacts import ArtifactStore
from .config import Settings
from .errors import NotFound, ValidationFailed
from .security import check_read_path, digest_bytes, redact, redact_url, scan_untrusted, check_url
from .store import Store, jdump, jload, new_id, now_iso, parse_iso

ORIGINS = ("tool_output", "local_file", "user_statement", "model_summary")
VERIFICATIONS = ("VERIFIED", "UNVERIFIED", "INFERRED", "UNKNOWN")
EXCERPT_LIMIT = 400


class EvidenceService:
    def __init__(self, settings: Settings, store: Store, artifacts: ArtifactStore):
        self.settings = settings
        self.store = store
        self.artifacts = artifacts

    def register(
        self,
        *,
        workflow_id: str | None,
        claim: str,
        origin: str,
        requested: str = "UNVERIFIED",
        source_ref: str | None = None,
        source_id: str | None = None,
        provider: str | None = None,
        content: str | bytes | None = None,
        excerpt: str | None = None,
        ttl_class: str = "default",
        retrieved_at: str | None = None,
        uncertainty: str | None = None,
        scan_content: bool = True,
        con=None,
    ) -> dict[str, Any]:
        if origin not in ORIGINS:
            raise ValidationFailed(f"origin must be one of {ORIGINS}")
        if requested not in VERIFICATIONS:
            raise ValidationFailed(f"verification must be one of {VERIFICATIONS}")
        if not claim.strip():
            raise ValidationFailed("claim is empty")
        notes: list[str] = []
        verification = requested
        stamp = retrieved_at or now_iso()
        try:
            if parse_iso(stamp) > datetime.now(UTC).replace(microsecond=0) and (parse_iso(stamp) - datetime.now(UTC)).total_seconds() > 60:
                notes.append("retrieved_at is in the future; reset to now")
                stamp = now_iso()
        except ValueError:
            raise ValidationFailed("retrieved_at must be ISO-8601 UTC like 2026-01-31T10:00:00.000000Z")

        if source_ref:
            if source_ref.startswith(("http://", "https://")):
                if not check_url(source_ref, resolve=False).ok:
                    notes.append("source_ref url failed syntax/policy check; cannot be VERIFIED")
                    verification = _cap(verification, "UNVERIFIED")
                source_ref = redact_url(source_ref)
            elif origin == "local_file":
                try:
                    check_read_path(source_ref, [])
                except Exception as e:
                    raise ValidationFailed(f"local source rejected: {e}")

        digest = None
        artifact_id = None
        flags: list[str] = []
        if content is not None:
            data = content.encode("utf-8") if isinstance(content, str) else content
            digest = digest_bytes(data)
            text = data[:200_000].decode("utf-8", errors="replace")
            flags = scan_untrusted(text) if scan_content else []
            art = self.artifacts.put(workflow_id, "evidence_raw", data, "text/plain", con=con)
            artifact_id = art["id"]
            if excerpt is None:
                excerpt = text[:EXCERPT_LIMIT]

        if origin == "model_summary":
            if verification == "VERIFIED":
                notes.append("model summaries are never original evidence; downgraded to INFERRED")
            verification = _cap(verification, "INFERRED")
        elif origin in ("tool_output", "local_file"):
            if verification == "VERIFIED" and not (source_ref and digest):
                notes.append("VERIFIED needs both source_ref and captured content digest; downgraded to UNVERIFIED")
                verification = "UNVERIFIED"
        elif origin == "user_statement":
            if verification == "VERIFIED" and not excerpt:
                notes.append("user statements need a quoted excerpt to be VERIFIED; downgraded to UNVERIFIED")
                verification = "UNVERIFIED"

        if flags:
            notes.append(f"untrusted content contains instruction-like patterns: {','.join(flags)}")

        eid = new_id("ev")
        safe_excerpt = redact(excerpt)[:EXCERPT_LIMIT] if excerpt else None
        unc = jdump({"note": uncertainty, "flags": flags, "downgrades": notes}) if (uncertainty or flags or notes) else None
        row = (
            eid, workflow_id, redact(claim)[:1000], origin, source_id, source_ref, provider, stamp, verification,
            unc, digest, artifact_id, safe_excerpt, ttl_class, now_iso(),
        )
        sql = (
            "INSERT INTO evidence(id,workflow_id,claim,origin,source_id,source_ref,provider,retrieved_at,verification,"
            "uncertainty,digest,artifact_id,excerpt,ttl_class,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        if con is not None:
            con.execute(sql, row)
        else:
            with self.store.tx() as c:
                c.execute(sql, row)
        return {
            "id": eid,
            "verification": verification,
            "requested": requested,
            "digest": digest,
            "artifact_id": artifact_id,
            "flags": flags,
            "notes": notes,
        }

    def get(self, evidence_id: str, con=None) -> dict[str, Any]:
        def q(c):
            return c.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()

        if con is not None:
            r = q(con)
        else:
            with self.store.read() as c:
                r = q(c)
        if r is None:
            raise NotFound(f"evidence '{evidence_id}' not found")
        d = dict(r)
        d["uncertainty"] = jload(d.get("uncertainty"), {})
        d["stale"] = self.is_stale(d)
        return d

    def list(self, workflow_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.store.read() as con:
            rows = con.execute(
                "SELECT id,claim,origin,verification,source_ref,retrieved_at,ttl_class,digest FROM evidence WHERE workflow_id=? ORDER BY created_at LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def is_stale(self, record: dict[str, Any]) -> bool:
        age = (datetime.now(UTC) - parse_iso(record["retrieved_at"])).total_seconds()
        return age > self.settings.ttl(record.get("ttl_class") or "default")

    def usable_as_verified(self, evidence_id: str, con=None, *, workflow_id: str | None = None) -> tuple[bool, str]:
        try:
            rec = self.get(evidence_id, con=con)
        except NotFound:
            return False, "evidence not found"
        if workflow_id is not None and rec["workflow_id"] != workflow_id:
            return False, "evidence belongs to a different workflow"
        if rec["verification"] != "VERIFIED":
            return False, f"evidence is {rec['verification']}, not VERIFIED"
        if rec["stale"]:
            return False, "evidence is stale"
        if (rec["uncertainty"] or {}).get("flags"):
            return False, "evidence content has injection flags; needs human review"
        return True, "ok"


def _cap(current: str, ceiling: str) -> str:
    order = {"UNKNOWN": 0, "INFERRED": 1, "UNVERIFIED": 2, "VERIFIED": 3}
    return current if order[current] <= order[ceiling] else ceiling
