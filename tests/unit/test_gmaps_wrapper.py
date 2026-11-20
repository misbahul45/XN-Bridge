from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".providers" / "gmaps" / "xn_gmaps_mcp.py"
spec = importlib.util.spec_from_file_location("xn_gmaps_mcp", PATH)
gm = importlib.util.module_from_spec(spec)
sys.modules["xn_gmaps_mcp"] = gm
spec.loader.exec_module(gm)

ROWS = [
    {"title": "PT Alpha Software", "category": "Software company", "address": "Jl. A 1, Surabaya", "website": "https://alpha.example", "phone": "+62 31 111",
     "review_rating": 4.6, "review_count": 20, "latitude": -7.25, "longitude": 112.75, "link": "https://www.google.com/maps/place/alpha",
     "user_reviews": [{"text": "great"}], "popular_times": {"x": 1}, "emails": ["hr@alpha.example"]},
    {"title": "CV Beta Digital", "category": "Web designer", "address": "Jl. B 2, Sidoarjo", "website": "", "images": ["x"]},
    {"category": "no title is dropped"},
]


class FakeDocker:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else "\n".join(json.dumps(r) for r in ROWS)
        self.error = error
        self.commands = []

    def __call__(self, cmd, name):
        self.commands.append(cmd)
        if self.error:
            raise gm.GmapsError(self.error)
        out = Path(cmd[cmd.index("-v", cmd.index("-v") + 4) + 1].split(":")[0])
        (out / "results.json").write_text(self.payload)


def run(tmp_path, runner=None, now=1_000_000.0, **kw):
    runner = runner or FakeDocker()
    return gm.search(kw.pop("query", "software house Surabaya"), runner=runner, home=tmp_path, clock=lambda: now, **kw), runner


def test_command_is_fixed_pinned_without_shell_and_mounts_inputs_read_only(tmp_path):
    out, docker = run(tmp_path, depth=2, lang="id", geo="-7.25,112.75", with_emails=True)
    cmd = docker.commands[0]
    assert cmd[0] == "docker" and gm.IMAGE in cmd and "@sha256:" in gm.IMAGE
    assert any(a.endswith(":/queries.txt:ro") for a in cmd) and "--memory" in cmd and "--security-opt" in cmd
    assert "-p" not in cmd and "--network" not in cmd and "--privileged" not in cmd
    assert cmd[cmd.index("-depth") + 1] == "2" and cmd[cmd.index("-c") + 1] == "1" and "-email" in cmd and "-geo" in cmd


def test_results_keep_only_useful_fields_and_drop_reviews_and_untitled_rows(tmp_path):
    out, _ = run(tmp_path)
    assert out["found"] == 2 and [p["title"] for p in out["places"]] == ["PT Alpha Software", "CV Beta Digital"]
    first = out["places"][0]
    assert "user_reviews" not in first and "popular_times" not in first and first["emails"] == ["hr@alpha.example"]
    assert "website" not in out["places"][1] and "images" not in out["places"][1]
    assert out["untrusted"] is True and "lead" in out["source"]


def test_json_array_output_is_also_accepted(tmp_path):
    out, _ = run(tmp_path, FakeDocker(json.dumps(ROWS)))
    assert out["found"] == 2


def test_max_places_truncates_but_the_saved_file_keeps_everything(tmp_path):
    out, _ = run(tmp_path, max_places=1)
    assert out["returned"] == 1 and out["found"] == 2
    saved = Path(out["saved_to"])
    assert len(json.loads(saved.read_text())["rows"]) == 2
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600 and stat.S_IMODE((tmp_path / "gmaps").stat().st_mode) == 0o700


def test_temporary_work_directory_is_removed(tmp_path):
    run(tmp_path)
    assert [p for p in (tmp_path / "gmaps").iterdir() if p.name.startswith("xn-gmaps-")] == []


@pytest.mark.parametrize("query", ["", "x", "a;rm -rf /", "$(id)", "line1\nline2 | cat", "q" * 121])
def test_hostile_or_invalid_queries_are_rejected(tmp_path, query):
    docker = FakeDocker()
    with pytest.raises(gm.GmapsError):
        gm.search(query, runner=docker, home=tmp_path, clock=lambda: 1.0)
    assert docker.commands == []


@pytest.mark.parametrize("kw", [{"lang": "../etc"}, {"geo": "abc"}, {"geo": "1,2;3"}])
def test_invalid_options_are_rejected(tmp_path, kw):
    with pytest.raises(gm.GmapsError):
        gm.search("software house Surabaya", runner=FakeDocker(), home=tmp_path, clock=lambda: 1.0, **kw)


def test_depth_and_places_are_clamped(tmp_path):
    out, docker = run(tmp_path, depth=99, max_places=999)
    assert docker.commands[0][docker.commands[0].index("-depth") + 1] == str(gm.MAX_DEPTH)


def test_one_run_per_minute_and_daily_cap(tmp_path):
    run(tmp_path, now=1_000_000.0)
    with pytest.raises(gm.GmapsError, match="wait"):
        run(tmp_path, now=1_000_030.0)
    run(tmp_path, now=1_000_100.0)
    t = 1_000_200.0
    for _ in range(gm.MAX_RUNS_PER_DAY):
        try:
            run(tmp_path, now=t)
        except gm.GmapsError as e:
            assert "daily limit" in str(e)
            break
        t += 70
    else:
        pytest.fail("daily cap never triggered")


def test_runner_failure_is_reported_and_leaves_no_work_dir(tmp_path):
    with pytest.raises(gm.GmapsError, match="exited"):
        run(tmp_path, FakeDocker(error="scraper exited with code 1"))
    assert [p for p in (tmp_path / "gmaps").iterdir() if p.name.startswith("xn-gmaps-")] == []


def test_empty_output_returns_no_places(tmp_path):
    out, _ = run(tmp_path, FakeDocker(payload=""))
    assert out["found"] == 0 and out["places"] == []


def test_mcp_server_exposes_one_tool_and_rejects_bad_input_over_stdio():
    from mcp import Client, StdioServerParameters

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[str(PATH)], env={})
        async with Client(params) as c:
            tools = (await c.list_tools()).tools
            bad = await c.call_tool("gmaps_search", {"query": "a;rm -rf /"})
            return tools, bad

    tools, bad = asyncio.run(go())
    assert [t.name for t in tools] == ["gmaps_search"] and tools[0].annotations.destructive_hint is False
    assert bad.is_error is True
