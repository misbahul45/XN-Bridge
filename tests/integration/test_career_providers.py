"""Installed providers: real host discovery and local-only security checks.

No mailbox credentials, employer writes or public-board requests are used here.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.host, pytest.mark.skipif(os.environ.get("XN_RUN_HOST_TESTS") != "1", reason="set XN_RUN_HOST_TESTS=1 for installed career/Gmail providers")]


def test_actual_codex_exposes_only_reviewed_provider_tools_and_blocks_send():
    from xnbridge.host_api import CodexHost
    from xnbridge.errors import Unavailable

    host = CodexHost(servers=["career-public", "gmail"])
    try:
        tid = host.start()
        inventory = {s["name"]: set(s.get("tools", {})) for s in host.inventory(timeout=45)}
        assert inventory["career-public"] == {"search_jobs", "latest_jobs", "jobs_by_board", "company_jobs", "job_categories"}
        assert inventory["gmail"] == {"search_gmail_messages", "get_gmail_message_content", "get_gmail_messages_content_batch"}
        result = host.request("mcpServer/tool/call", {"threadId": tid, "server": "career-public", "tool": "job_categories", "arguments": {}})
        assert not result.get("isError") and "Jobicy" in result["content"][0]["text"]
        with pytest.raises(Unavailable, match="disabled"):
            host.request("mcpServer/tool/call", {"threadId": tid, "server": "gmail", "tool": "send_gmail_message", "arguments": {}})
    finally:
        host.close()


def test_gmail_callback_validates_host_origin_and_strict_state_without_credentials():
    code = '''
import runpy, os, json
from starlette.testclient import TestClient
ns = runpy.run_path("scripts/gmail_stdio.py")
ns["configure"]()
from auth.oauth_callback_server import MinimalOAuthServer
server = MinimalOAuthServer(port=8000, base_uri="http://127.0.0.1")
with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
    assert client.get("/oauth2callback").status_code == 400
    bad = client.get("/oauth2callback", headers={"host":"attacker.example"})
    assert bad.status_code == 400 and "Invalid host" in bad.text
    assert client.get("/oauth2callback", headers={"origin":"https://attacker.example"}).status_code == 403
    assert client.get("/oauth2callback", headers={"origin":"null"}).status_code == 403
    assert client.get("/oauth2callback", headers={"origin":"http://127.0.0.1:8000"}).status_code == 400
assert os.environ["MCP_SINGLE_USER_MODE"] == "0"
assert os.environ["OTEL_SDK_DISABLED"] == "true"
print(json.dumps({"host_origin":"PASS", "strict_state":True}))
'''
    p = subprocess.run([str(ROOT / ".providers/gmail/bin/python"), "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr[-1500:]
    assert json.loads(p.stdout)["strict_state"] is True


def test_gmail_bootstrap_uses_upstream_pkce_state_and_readonly_scopes_without_network():
    code = '''
import asyncio, json, sys, tempfile, re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
sys.path.insert(0, str(Path("scripts").resolve()))
import connect_gmail as setup
with tempfile.TemporaryDirectory() as tmp:
    setup.PRIVATE = Path(tmp)
    setup.CLIENT = Path(tmp) / "client.json"
    setup.CLIENT.write_text(json.dumps({"installed": {"client_id":"12345-test.apps.googleusercontent.com", "client_secret":"synthetic-secret", "auth_uri":"https://accounts.google.com/o/oauth2/auth", "token_uri":"https://oauth2.googleapis.com/token", "redirect_uris":["http://localhost"]}}))
    scopes = setup.configure_provider()
    assert set(scopes) == setup.SAFE_SCOPES
    from auth.google_auth import start_auth_flow
    with patch("webbrowser.open", return_value=False):
        message = asyncio.run(start_auth_flow(None, "Gmail", "http://127.0.0.1:8000/oauth2callback"))
    url = re.search(r"https://accounts\\.google\\.com/[^\\s<>\\)]+", message).group(0)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) > 30
    assert len(query["state"][0]) >= 32
    assert set(query["scope"][0].split()) == setup.SAFE_SCOPES
    assert "synthetic-secret" not in url
print(json.dumps({"pkce":"PASS", "readonly":True, "network_calls":0}))
'''
    p = subprocess.run([str(ROOT / ".providers/gmail/bin/python"), "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr[-1500:]
    assert json.loads(p.stdout)["pkce"] == "PASS"
