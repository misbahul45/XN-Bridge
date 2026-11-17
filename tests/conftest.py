from __future__ import annotations

import os
from pathlib import Path

import pytest

from xnbridge.app import Bridge, build


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    return tmp_path / "xn-home"


@pytest.fixture()
def bridge(home: Path) -> Bridge:
    return build(home)


@pytest.fixture()
def research_wf(bridge: Bridge) -> dict:
    return bridge.engine.create("research", "unit")


def pytest_collection_modifyitems(config, items):
    skip_host = pytest.mark.skip(reason="set XN_RUN_HOST_TESTS=1 to run against the real Codex host")
    skip_live = pytest.mark.skip(reason="set XN_RUN_LIVE_TESTS=1 to use the public internet")
    for item in items:
        if "host" in item.keywords and not os.environ.get("XN_RUN_HOST_TESTS"):
            item.add_marker(skip_host)
        if "live" in item.keywords and not os.environ.get("XN_RUN_LIVE_TESTS"):
            item.add_marker(skip_live)
