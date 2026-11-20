from __future__ import annotations

import asyncio
import base64
import email
import importlib.util
import json
import os
import sqlite3
import stat
import sys
from email import policy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".providers" / "gmail_send" / "xn_gmail_send.py"
spec = importlib.util.spec_from_file_location("xn_gmail_send", PATH)
gs = importlib.util.module_from_spec(spec)
sys.modules["xn_gmail_send"] = gs
spec.loader.exec_module(gs)

DAY = 1_800_000_000.0


class FakeService:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent.append(body["raw"])
        return self

    def execute(self):
        if self.error:
            raise self.error
        return {"id": f"msg{len(self.sent)}", "threadId": "thr1"}


@pytest.fixture()
def root(tmp_path):
    home = tmp_path / "data"
    (home / "private").mkdir(parents=True)
    con = sqlite3.connect(home / "bridge.db")
    con.execute("CREATE TABLE entities (id TEXT, workflow_id TEXT, kind TEXT, data_json TEXT)")
    con.execute("INSERT INTO entities VALUES ('c1','w1','company',?)", (json.dumps({"domains": [{"domain": "northwind.example", "verified": True}, {"domain": "pending.example", "verified": False}]}),))
    con.commit()
    con.close()
    return home


def do(root, to="hr@northwind.example", subject="Application: Backend Intern", body="Hello, I would like to apply.", attachments=None, service=None, now=DAY):
    service = service or FakeService()
    out = gs.send(to, subject, body, attachments, root=root, service_factory=lambda r: service, clock=lambda: now)
    return out, service


def decode(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)


def test_send_builds_a_plain_message_and_returns_the_gmail_message_id(root):
    out, svc = do(root)
    assert out["message_id"] == "msg1" and out["thread_id"] == "thr1" and out["sent_today"] == 1
    msg = decode(svc.sent[0])
    assert msg["To"] == "hr@northwind.example" and msg["Subject"] == "Application: Backend Intern" and "apply" in msg.get_content()


def test_state_file_is_private_and_records_the_attempt(root):
    do(root)
    state_path = root / "gmail-send" / "state.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600 and stat.S_IMODE((root / "gmail-send").stat().st_mode) == 0o700
    assert json.loads(state_path.read_text())["sent"][0]["status"] == "SENT"


@pytest.mark.parametrize("to", ["a@x.example, b@y.example", "hr@northwind.example\nbcc: evil@x.example", "not-an-address", "hr@", "Name <hr@northwind.example>", ""])
def test_malformed_or_multiple_recipients_are_rejected(root, to):
    svc = FakeService()
    with pytest.raises(gs.SendError):
        do(root, to=to, service=svc)
    assert svc.sent == []


def test_recipient_must_be_on_a_verified_company_domain(root):
    svc = FakeService()
    for to in ("someone@attacker.example", "hr@pending.example", "hr@northwind.example.evil.example"):
        with pytest.raises(gs.SendError, match="verified company domain"):
            do(root, to=to, service=svc)
    assert svc.sent == []
    assert do(root, to="jobs@hr.northwind.example")[0]["message_id"]


def test_owner_allow_list_permits_an_extra_address_only(root):
    (root / "private" / "gmail-send-allow.txt").write_text("# own address\nme@example.org\n")
    assert do(root, to="me@example.org")[0]["message_id"]
    with pytest.raises(gs.SendError):
        do(root, to="other@example.org")


@pytest.mark.parametrize("subject", ["", "x" * 201, "Hi\r\nBcc: evil@x.example"])
def test_subject_must_be_one_short_line(root, subject):
    with pytest.raises(gs.SendError):
        do(root, subject=subject)


def test_body_must_be_present_and_bounded(root):
    with pytest.raises(gs.SendError):
        do(root, body="   ")
    with pytest.raises(gs.SendError):
        do(root, body="x" * (gs.MAX_BODY + 1))


def test_exact_duplicate_is_blocked_but_a_different_subject_is_not(root):
    do(root)
    with pytest.raises(gs.SendError, match="already sent"):
        do(root)
    assert do(root, subject="Follow up")[0]["sent_today"] == 2


def test_per_recipient_and_daily_caps(root):
    do(root, subject="a")
    do(root, subject="b")
    with pytest.raises(gs.SendError, match="to this recipient"):
        do(root, subject="c")
    for i in range(gs.MAX_PER_DAY - 2):
        do(root, to=f"hr{i}@northwind.example", subject="x")
    with pytest.raises(gs.SendError, match="daily limit"):
        do(root, to="last@northwind.example", subject="x")


def test_caps_reset_on_a_new_day_but_duplicates_stay_blocked(root):
    do(root)
    with pytest.raises(gs.SendError, match="already sent"):
        do(root, now=DAY + 90_000)


def test_stop_file_blocks_sending(root):
    (root / "STOP_EXTERNAL").write_text("")
    svc = FakeService()
    with pytest.raises(gs.SendError, match="stop file"):
        do(root, service=svc)
    assert svc.sent == []


def test_attachment_inside_allowed_folder_is_attached(root):
    out_dir = root / "outgoing"
    out_dir.mkdir()
    cv = out_dir / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 fixture")
    out, svc = do(root, attachments=[str(cv)])
    msg = decode(svc.sent[0])
    parts = [p.get_filename() for p in msg.iter_attachments()]
    assert parts == ["cv.pdf"] and out["attachments"] == ["cv.pdf"]


def test_attachment_outside_allowed_folders_or_with_wrong_type_is_rejected(root, tmp_path):
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"x")
    with pytest.raises(gs.SendError, match="outside"):
        do(root, attachments=[str(outside)])
    out_dir = root / "outgoing"
    out_dir.mkdir()
    exe = out_dir / "run.sh"
    exe.write_text("echo")
    with pytest.raises(gs.SendError, match="must be an existing"):
        do(root, attachments=[str(exe)])


def test_symlink_escape_from_the_allowed_folder_is_rejected(root, tmp_path):
    out_dir = root / "outgoing"
    out_dir.mkdir()
    target = tmp_path / "private.pdf"
    target.write_bytes(b"x")
    (out_dir / "link.pdf").symlink_to(target)
    with pytest.raises(gs.SendError, match="outside"):
        do(root, attachments=[str(out_dir / "link.pdf")])


def test_attachment_count_and_size_limits(root):
    out_dir = root / "outgoing"
    out_dir.mkdir()
    big = out_dir / "big.pdf"
    big.write_bytes(b"0" * (gs.MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(gs.SendError, match="5 MB"):
        do(root, attachments=[str(big)])
    files = []
    for i in range(gs.MAX_ATTACHMENTS + 1):
        f = out_dir / f"f{i}.txt"
        f.write_text("x")
        files.append(str(f))
    with pytest.raises(gs.SendError, match="at most"):
        do(root, attachments=files)


def test_failed_send_is_reported_as_unknown_and_never_retried_with_the_same_message(root):
    svc = FakeService(error=TimeoutError("timed out"))
    with pytest.raises(gs.SendError, match="OUTCOME_UNKNOWN"):
        do(root, service=svc)
    state = json.loads((root / "gmail-send" / "state.json").read_text())
    assert state["sent"][0]["status"] == "OUTCOME_UNKNOWN"
    with pytest.raises(gs.SendError, match="already sent"):
        do(root)


def test_missing_token_gives_a_clear_authorization_error(root):
    with pytest.raises(gs.SendError, match="not authorized"):
        gs.credentials(root)


def test_status_reports_authorization_stop_and_count(root):
    assert gs.status(root)["authorized"] is False and gs.status(root)["scope"].endswith("gmail.send")
    (root / "private" / "gmail-send-token.json").write_text("{}")
    (root / "STOP_EXTERNAL").write_text("")
    s = gs.status(root)
    assert s["authorized"] is True and s["stopped"] is True


def test_mcp_server_exposes_two_tools_and_refuses_without_authorization():
    from mcp import Client, StdioServerParameters

    async def go():
        env = {"XN_BRIDGE_HOME": str(Path(os.environ.get("TMPDIR", "/tmp")) / "xn-gmail-send-nonexistent")}
        params = StdioServerParameters(command=sys.executable, args=[str(PATH)], env=env)
        async with Client(params) as c:
            tools = (await c.list_tools()).tools
            bad = await c.call_tool("gmail_send", {"to": "someone@attacker.example", "subject": "s", "body": "b"})
            return tools, bad

    tools, bad = asyncio.run(go())
    assert {t.name for t in tools} == {"gmail_send", "gmail_send_status"}
    assert bad.is_error is True
