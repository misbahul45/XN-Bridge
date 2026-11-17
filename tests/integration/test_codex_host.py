import os

import pytest


@pytest.mark.host
@pytest.mark.skipif(os.environ.get("XN_RUN_HOST_TESTS") != "1", reason="set XN_RUN_HOST_TESTS=1 to exercise installed Codex app-server")
def test_t22_real_codex_host():
    from scripts.check_codex_host import check
    result = check()
    assert result["ok"] and result["checkpoint_resume"] == "PASS"
    assert result["model_calls"] == 0


@pytest.mark.host
@pytest.mark.skipif(os.environ.get("XN_RUN_HOST_TESTS") != "1", reason="set XN_RUN_HOST_TESTS=1 for native catalog integration")
def test_real_codex_host_catalog_uses_host_owned_provider_connections(bridge):
    from xnbridge.hosts import load_host_servers
    from xnbridge.host_catalog import sync_host_catalog
    report = sync_host_catalog(bridge, load_host_servers("codex"), only=["web_search"], timeout=25)
    assert report["ok"] and report["model_calls"] == 0
    assert report["servers"][0]["tools"] > 0
    assert bridge.registry.contract("web_search", "search")["contract"]["inputSchema"]["type"] == "object"
