import json
from argparse import Namespace

import pytest

from tests.career_helpers import ready_submission, grant_for, begin_submit
from xnbridge import entities
from xnbridge.cli import _render_payload, cmd_approve
from xnbridge.errors import ApprovalError
from xnbridge.cli import _terminal


def test_generic_approval_payload_is_displayed_in_full(bridge, capsys):
    wf = bridge.engine.create("research")["id"]
    text = "x" * 6500 + "END-OF-EXACT-CONTENT"
    approval = bridge.approvals.prepare(workflow_id=wf, action_kind="email.send", target="https://mail.example.org/send", payload={"message": text})
    assert _render_payload(bridge, approval) is True
    assert "END-OF-EXACT-CONTENT" in capsys.readouterr().out


def test_missing_attachment_prevents_signing_even_when_terminal_is_present(bridge, monkeypatch):
    ctx = ready_submission(bridge, monkeypatch)
    approval = bridge.approvals.prepare(workflow_id=ctx["wf"], action_kind="application.submit", target=ctx["target"], payload_ref=f"entity:{ctx['manifest_id']}")
    with bridge.store.read() as con:
        manifest = entities.get(con, ctx["manifest_id"])["data"]
    meta = bridge.artifacts.meta(manifest["attachments"][0]["artifact_id"])
    (bridge.settings.artifacts_dir / meta["rel_path"]).unlink()
    monkeypatch.setattr("xnbridge.cli._need_tty", lambda _: True)
    monkeypatch.setattr("xnbridge.cli.build", lambda: bridge)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not request confirmation for an incomplete payload"))
    assert cmd_approve(Namespace(approval_id=approval["approval_id"])) == 1


def test_attachment_tampering_after_grant_is_rejected_before_execution(bridge, monkeypatch):
    ctx = ready_submission(bridge, monkeypatch)
    approval = grant_for(bridge, ctx)
    with bridge.store.read() as con:
        manifest = entities.get(con, ctx["manifest_id"])["data"]
    meta = bridge.artifacts.meta(manifest["attachments"][0]["artifact_id"])
    (bridge.settings.artifacts_dir / meta["rel_path"]).write_bytes(b"changed after review")
    with pytest.raises(ApprovalError):
        begin_submit(bridge, ctx, approval)


def test_terminal_control_characters_are_visible_during_review():
    assert "\x1b" not in _terminal("\x1b[2Jhidden\u202e")
    assert r"\x1b" in _terminal("\x1b[2Jhidden\u202e")
