from __future__ import annotations

import json
import copy
import stat
import zipfile

import pytest

from xnbridge.app import build
from xnbridge.backup import create_full_backup, restore_full_backup
from xnbridge.errors import ValidationFailed


def test_full_state_roundtrip_preserves_evidence_artifacts_config_and_both_domains(bridge, tmp_path):
    wf = bridge.engine.create("research")["id"]
    bridge.engine.create("career")
    bridge.engine.checkpoint(wf, "collect", "DONE")
    ev = bridge.evidence.register(workflow_id=wf, claim="Local source", origin="tool_output", requested="VERIFIED", source_ref="https://example.org/source", content="Captured source data")
    (bridge.settings.config_dir / "policy.toml").write_text("[network]\noffline = true\n")
    archive = tmp_path / "state.zip"
    snapshot = create_full_backup(bridge, archive)
    assert snapshot["artifacts"] >= 1 and archive.stat().st_mode & 0o777 == 0o600
    restored_home = tmp_path / "restored"
    report = restore_full_backup(archive, restored_home)
    restored = build(restored_home)
    assert report["integrity"] == "ok" and restored.store.integrity()["ok"]
    assert restored.engine.resume(wf)["next_action"]["stage"] == "verify"
    assert len(restored.engine.list()) == 2
    record = restored.evidence.get(ev["id"])
    assert restored.artifacts.read_text(record["artifact_id"]) == "Captured source data"
    assert restored.settings.policy["network"]["offline"] is True


def test_snapshot_rejects_missing_artifact_and_does_not_publish_partial_backup(bridge, tmp_path):
    art = bridge.artifacts.put(None, "fixture", "original")
    meta = bridge.artifacts.meta(art["id"])
    (bridge.settings.artifacts_dir / meta["rel_path"]).write_text("corrupt")
    archive = tmp_path / "broken.zip"
    with pytest.raises(ValidationFailed):
        create_full_backup(bridge, archive)
    assert not archive.exists()


def test_restore_never_overwrites_existing_state(bridge, tmp_path):
    archive = tmp_path / "state.zip"
    create_full_backup(bridge, archive)
    with pytest.raises(ValidationFailed):
        restore_full_backup(archive, bridge.settings.home)
    with pytest.raises(ValidationFailed):
        create_full_backup(bridge, archive)


@pytest.mark.parametrize("kind", ["tampered", "traversal", "symlink", "duplicate", "unlisted"])
def test_restore_rejects_untrusted_archive_before_publishing(bridge, tmp_path, kind):
    original = tmp_path / "original.zip"
    create_full_backup(bridge, original)
    bad = tmp_path / f"{kind}.zip"
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(bad, "w") as out:
        for item in src.infolist():
            content = src.read(item.filename)
            if kind == "tampered" and item.filename == "bridge.db":
                content += b"tamper"
            out.writestr(copy.copy(item), content)
        if kind == "traversal":
            out.writestr("../escape", "no")
        elif kind == "symlink":
            item = zipfile.ZipInfo("config/link")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            out.writestr(item, "/etc/passwd")
        elif kind == "duplicate":
            with pytest.warns(UserWarning):
                out.writestr("manifest.json", src.read("manifest.json"))
        elif kind == "unlisted":
            out.writestr("config/extra", "not in the manifest")
    target = tmp_path / "restored"
    with pytest.raises(ValidationFailed):
        restore_full_backup(bad, target)
    assert not target.exists() and not (tmp_path / "escape").exists()


def test_backup_and_restore_enforce_size_bounds(bridge, tmp_path):
    archive = tmp_path / "state.zip"
    with pytest.raises(ValidationFailed):
        create_full_backup(bridge, archive, max_bytes=100)
    create_full_backup(bridge, archive)
    with pytest.raises(ValidationFailed):
        restore_full_backup(archive, tmp_path / "restored", max_bytes=100)


def test_snapshot_does_not_follow_config_symlinks(bridge, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private outside data")
    (bridge.settings.config_dir / "link.toml").symlink_to(outside)
    with pytest.raises(ValidationFailed):
        create_full_backup(bridge, tmp_path / "state.zip")


def test_restore_revokes_old_grants_and_requires_reconciliation_for_started_writes(bridge, tmp_path, monkeypatch):
    from tests.career_helpers import ready_submission, grant_for, begin_submit
    ctx = ready_submission(bridge, monkeypatch)
    first = grant_for(bridge, ctx)
    execution = begin_submit(bridge, ctx, first)
    unused = grant_for(bridge, ctx)
    fingerprint = bridge.approvals.fingerprint()
    archive = tmp_path / "state.zip"
    create_full_backup(bridge, archive)
    destination = tmp_path / "restored"
    report = restore_full_backup(archive, destination)
    restored = build(destination)
    assert report["revoked_approvals"] == 1 and report["uncertain_executions"] == 1
    assert restored.approvals.status(unused)["state"] == "REVOKED"
    assert restored.approvals.fingerprint() == fingerprint
    assert restored.engine.get(ctx["wf"])["state"] == "RECONCILIATION_REQUIRED"
    assert restored.executions.list(ctx["wf"])[0]["state"] == "OUTCOME_UNKNOWN"
    assert bridge.executions.list(ctx["wf"])[0]["state"] == "STARTED"
