from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .artifacts import ArtifactStore
from .config import Settings
from .errors import ApprovalError, BridgeError, NotFound, ValidationFailed
from .security import canonical_json, digest_obj, file_mode_private, origin_of
from .store import Store, jdump, jload, new_id, now_iso, parse_iso

STATEMENT_VERSION = 1


def statement_bytes(row: dict[str, Any]) -> bytes:
    return canonical_json(
        {
            "v": STATEMENT_VERSION,
            "approval_id": row["id"],
            "workflow_id": row["workflow_id"],
            "action_kind": row["action_kind"],
            "target": row["target"],
            "target_origin": row["target_origin"],
            "payload_digest": row["payload_digest"],
            "expires_at": row["expires_at"],
        }
    ).encode("utf-8")


def key_fingerprint(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


class ApprovalService:
    def __init__(self, settings: Settings, store: Store, artifacts: ArtifactStore):
        self.settings = settings
        self.store = store
        self.artifacts = artifacts

    def generate_keypair(self, passphrase: bytes) -> str:
        if not passphrase:
            raise ValidationFailed("passphrase required")
        self.settings.ensure_dirs()
        if self.settings.approver_key.exists() or self.settings.approver_pub.exists():
            raise ValidationFailed("approver key already exists; refusing to overwrite")
        priv = Ed25519PrivateKey.generate()
        enc = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(passphrase),
        )
        pub = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.settings.approver_key.write_bytes(enc)
        self.settings.approver_key.chmod(0o600)
        self.settings.approver_pub.write_bytes(pub)
        self.settings.approver_pub.chmod(0o644)
        fp = key_fingerprint(priv.public_key())
        with self.store.tx() as con:
            self.store.audit(con, "human-cli", "approver_key_created", {"fingerprint": fp})
        return fp

    def public_key(self) -> Ed25519PublicKey | None:
        p = self.settings.approver_pub
        if not p.is_file():
            return None
        key = serialization.load_pem_public_key(p.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValidationFailed("approver.pub is not an Ed25519 key")
        return key

    def fingerprint(self) -> str | None:
        k = self.public_key()
        return key_fingerprint(k) if k else None

    def key_health(self) -> dict[str, Any]:
        return {
            "configured": self.settings.approver_pub.is_file() and self.settings.approver_key.is_file(),
            "fingerprint": self.fingerprint(),
            "private_key_mode_ok": file_mode_private(self.settings.approver_key) if self.settings.approver_key.is_file() else None,
        }

    def prepare(
        self,
        *,
        workflow_id: str,
        action_kind: str,
        target: str,
        payload: dict[str, Any] | None = None,
        payload_ref: str | None = None,
        summary: dict[str, Any] | None = None,
        ttl_s: int | None = None,
    ) -> dict[str, Any]:
        if (payload is None) == (payload_ref is None):
            raise ValidationFailed("provide exactly one of payload or payload_ref")
        origin = origin_of(target)
        ttl = ttl_s if ttl_s is not None else self.settings.limit("approval_ttl_s")
        ttl = max(60, min(ttl, 86400))
        with self.store.tx() as con:
            if con.execute("SELECT 1 FROM workflows WHERE id=?", (workflow_id,)).fetchone() is None:
                raise NotFound(f"workflow '{workflow_id}' not found")
            if payload is not None:
                art = self.artifacts.put(workflow_id, "approval_payload", canonical_json(payload), "application/json", con=con)
                ref = f"artifact:{art['id']}"
                digest = digest_obj(payload)
            else:
                ref = payload_ref
                digest = self.digest_for_ref(con, workflow_id, ref)
            existing = con.execute(
                "SELECT * FROM approvals WHERE workflow_id=? AND action_kind=? AND target=? AND payload_digest=? AND state IN ('PENDING','GRANTED') AND expires_at>?",
                (workflow_id, action_kind, target, digest, now_iso()),
            ).fetchone()
            if existing:
                out = self._public(dict(existing))
                out["reused"] = True
                return out
            aid = new_id("apr")
            created = datetime.now(UTC)
            expires = (created + timedelta(seconds=ttl)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            con.execute(
                "INSERT INTO approvals(id,workflow_id,action_kind,target,target_origin,payload_ref,payload_digest,summary_json,state,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (aid, workflow_id, action_kind, target, origin, ref, digest, jdump(summary or {}), "PENDING", now_iso(), expires),
            )
            self.store.audit(con, "bridge", "approval_prepared", {"approval_id": aid, "workflow_id": workflow_id, "action_kind": action_kind, "origin": origin})
            row = dict(con.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone())
        return self._public(row)

    def digest_for_ref(self, con, workflow_id: str, ref: str) -> str:
        kind, _, ident = ref.partition(":")
        if kind == "entity":
            r = con.execute("SELECT kind,data_json FROM entities WHERE id=? AND workflow_id=?", (ident, workflow_id)).fetchone()
            if r is None:
                raise NotFound(f"entity '{ident}' not found in workflow")
            payload = jload(r["data_json"])
            if r["kind"] == "submission_manifest":
                try:
                    refs = [*payload.get("texts", {}).values(), *payload.get("attachments", [])]
                    for ref in refs:
                        meta, _ = self.artifacts.read(ref["artifact_id"])
                        if meta["workflow_id"] != workflow_id or meta["digest"] != ref["digest"] or ("bytes" in ref and meta["bytes"] != ref["bytes"]):
                            raise ApprovalError("manifest attachment or text no longer matches its approved content")
                except (BridgeError, KeyError, TypeError) as e:
                    raise ApprovalError("payload changed or a manifest text/attachment cannot be verified; prepare it again") from e
            return digest_obj(payload)
        if kind == "artifact":
            r = con.execute("SELECT digest FROM artifacts WHERE id=? AND workflow_id=?", (ident, workflow_id)).fetchone()
            if r is None:
                raise NotFound(f"artifact '{ident}' not found")
            _, data = self.artifacts.read(ident)
            try:
                return digest_obj(jload(data.decode("utf-8")))
            except Exception:
                return hashlib.sha256(data).hexdigest()
        raise ValidationFailed("payload_ref must look like entity:<id> or artifact:<id>")

    def get(self, approval_id: str, con=None) -> dict[str, Any]:
        def q(c):
            return c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()

        if con is not None:
            r = q(con)
        else:
            with self.store.read() as c:
                r = q(c)
        if r is None:
            raise NotFound(f"approval '{approval_id}' not found")
        return dict(r)

    def status(self, approval_id: str) -> dict[str, Any]:
        row = self.get(approval_id)
        if row["state"] in ("PENDING", "GRANTED") and parse_iso(row["expires_at"]) < datetime.now(UTC):
            with self.store.tx() as con:
                con.execute("UPDATE approvals SET state='EXPIRED' WHERE id=? AND state IN ('PENDING','GRANTED')", (approval_id,))
            row = self.get(approval_id)
        return self._public(row)

    def grant(self, approval_id: str, private_key: Ed25519PrivateKey) -> dict[str, Any]:
        with self.store.tx() as con:
            row = self.get(approval_id, con)
            if row["state"] != "PENDING":
                raise ApprovalError(f"approval is {row['state']}, not PENDING")
            if parse_iso(row["expires_at"]) < datetime.now(UTC):
                con.execute("UPDATE approvals SET state='EXPIRED' WHERE id=?", (approval_id,))
                raise ApprovalError("approval expired before it was granted")
            current_digest = self.digest_for_ref(con, row["workflow_id"], row["payload_ref"])
            if current_digest != row["payload_digest"]:
                raise ApprovalError("payload changed after the approval was prepared; prepare a new approval")
            pub = private_key.public_key()
            registered = self.public_key()
            if registered is None or key_fingerprint(registered) != key_fingerprint(pub):
                raise ApprovalError("signing key does not match the registered approver.pub")
            sig = base64.b64encode(private_key.sign(statement_bytes(row))).decode()
            con.execute(
                "UPDATE approvals SET state='GRANTED', granted_at=?, signature=?, summary_json=? WHERE id=?",
                (now_iso(), sig, jdump({**jload(row["summary_json"], {}), "signer_fp": key_fingerprint(pub)}), approval_id),
            )
            self.store.audit(con, "human-cli", "approval_granted", {"approval_id": approval_id, "fingerprint": key_fingerprint(pub)})
            return self._public(self.get(approval_id, con))

    def reject(self, approval_id: str) -> dict[str, Any]:
        with self.store.tx() as con:
            row = self.get(approval_id, con)
            if row["state"] not in ("PENDING", "GRANTED"):
                raise ApprovalError(f"approval is {row['state']}")
            con.execute("UPDATE approvals SET state='REJECTED' WHERE id=?", (approval_id,))
            self.store.audit(con, "human-cli", "approval_rejected", {"approval_id": approval_id})
            return self._public(self.get(approval_id, con))

    def verify_and_consume(self, con, *, approval_id: str, workflow_id: str, target: str, execution_id: str) -> dict[str, Any]:
        row = self.get(approval_id, con)
        if row["workflow_id"] != workflow_id:
            raise ApprovalError("approval belongs to a different workflow")
        if row["state"] != "GRANTED":
            raise ApprovalError(f"approval is {row['state']}; a human must grant it first" if row["state"] == "PENDING" else f"approval is {row['state']} and cannot be used")
        if parse_iso(row["expires_at"]) < datetime.now(UTC):
            con.execute("UPDATE approvals SET state='EXPIRED' WHERE id=?", (approval_id,))
            raise ApprovalError("approval expired")
        if origin_of(target) != row["target_origin"] or target != row["target"]:
            raise ApprovalError("target differs from the approved target")
        pub = self.public_key()
        if pub is None:
            raise ApprovalError("no approver key registered; run `xnbridge approval-init`")
        signer = jload(row["summary_json"], {}).get("signer_fp")
        if signer != key_fingerprint(pub):
            raise ApprovalError("approval was signed by a different key than the current approver.pub")
        try:
            pub.verify(base64.b64decode(row["signature"] or ""), statement_bytes(row))
        except (InvalidSignature, ValueError):
            raise ApprovalError("approval signature invalid")
        now_digest = self.digest_for_ref(con, workflow_id, row["payload_ref"])
        if now_digest != row["payload_digest"]:
            raise ApprovalError("payload changed after approval; approval invalidated", details={"approved": row["payload_digest"][:12], "current": now_digest[:12]})
        cur = con.execute(
            "UPDATE approvals SET state='CONSUMED', consumed_at=?, consumed_by=? WHERE id=? AND state='GRANTED'",
            (now_iso(), execution_id, approval_id),
        )
        if cur.rowcount != 1:
            raise ApprovalError("approval already consumed")
        self.store.audit(con, "bridge", "approval_consumed", {"approval_id": approval_id, "execution_id": execution_id})
        return row

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        remaining = None
        if row["state"] in ("PENDING", "GRANTED"):
            remaining = max(0, int((parse_iso(row["expires_at"]) - datetime.now(UTC)).total_seconds()))
        out = {
            "approval_id": row["id"],
            "workflow_id": row["workflow_id"],
            "state": row["state"],
            "action_kind": row["action_kind"],
            "target": row["target"],
            "payload_digest": row["payload_digest"],
            "payload_ref": row["payload_ref"],
            "expires_at": row["expires_at"],
            "expires_in_s": remaining,
            "summary": jload(row["summary_json"], {}),
        }
        if row["state"] == "PENDING":
            out["human_step"] = f"ask the user to run in their own terminal: xnbridge approve {row['id']}"
        return out
