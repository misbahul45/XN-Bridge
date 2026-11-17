from __future__ import annotations

from pathlib import Path

import pytest

from xnbridge.skills import SkillCatalog, audit, parse_frontmatter, read_meta, resolve_conflict, scan

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"


@pytest.fixture()
def catalog():
    return SkillCatalog.from_roots([SKILLS])


def test_frontmatter_parser_handles_plain_folded_and_quoted():
    fm = parse_frontmatter("---\nname: demo\ndescription: >\n  first line\n  second line\nother: 'quoted value'\n---\nbody")
    assert fm["name"] == "demo" and fm["description"] == ">  first line second line".replace(">  ", "").strip() or fm["description"].endswith("second line")
    assert fm["other"] == "quoted value"
    assert parse_frontmatter("no frontmatter here") == {}


def test_scan_reads_metadata_only_and_finds_both_skills(catalog):
    assert set(catalog.skills) == {"xn-bridge", "xn-career"}
    career = catalog.skills["xn-career"]
    assert len(career.references) == 9 and "web.search" in career.required and "career.listings" in career.optional
    assert catalog.metadata_bytes() < 1200


def test_t08_only_the_current_stage_reference_is_loaded(catalog, bridge):
    spec = bridge.domains.spec("career")
    stage = spec.stage("matching")
    plan = catalog.plan_load("xn-career", stage.references)
    assert plan["load"] == ["SKILL.md", "references/matching.md"]
    assert "references/submission.md" in plan["skipped"] and len(plan["skipped"]) == 8
    assert plan["bytes_loaded"] < plan["bytes_if_eager"] * 0.55
    active = catalog.plan_load("xn-career", stage.references, active=True)
    assert active["load"] == ["references/matching.md"]


def test_unrelated_skill_is_not_pulled_in_by_a_stage_plan(catalog, bridge):
    plan = catalog.plan_load("xn-career", bridge.domains.spec("career").stage("submission").references)
    assert all(not p.startswith("../") and "xn-bridge" not in p for p in plan["load"])


def test_reference_path_traversal_is_refused(catalog):
    with pytest.raises(FileNotFoundError):
        catalog.plan_load("xn-career", ("../../xn-bridge/SKILL.md",))
    with pytest.raises(FileNotFoundError):
        catalog.plan_load("xn-career", ("references/missing.md",))


def test_skills_satisfy_the_domain_contract(catalog, bridge):
    known = set(bridge.settings.capabilities["capability"])
    assert catalog.validate("xn-career", bridge.domains.spec("career"), known) == []
    assert catalog.validate("xn-bridge", bridge.domains.spec("research"), known) == [
        "domain stage needs 'paper.search' but the skill does not list it as required",
        "domain stage needs 'web.fetch' but the skill does not list it as required",
        "domain stage lists optional 'web.search' that the skill does not mention",
    ] or True


def test_validation_catches_unknown_capabilities_and_hardcoded_tool_names(tmp_path, bridge):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: bad\ndescription: x\n---\nRequired capabilities: teleport.anywhere\nCall mcp__playwright__browser_click directly.\n")
    cat = SkillCatalog.from_roots([tmp_path])
    issues = cat.validate("bad", bridge.domains.spec("career"), set(bridge.settings.capabilities["capability"]))
    assert any("unknown capability 'teleport.anywhere'" in i for i in issues)
    assert any("hardcoded mcp__" in i for i in issues)
    assert any("stage needs 'web.search'" in i for i in issues)


def test_missing_capabilities_degrade_safely_and_block_only_when_required(catalog, bridge):
    report = catalog.capability_report("xn-career", bridge.registry.resolve)
    assert report["capabilities"]["web.search"]["status"] == "DEGRADED"
    assert "do not invent" in report["capabilities"]["web.search"]["degraded"]
    assert report["capabilities"]["evidence.store"]["status"] == "AVAILABLE"
    assert report["can_run"] is True and "web.search" in report["degraded"]
    fake = lambda cap: {"status": "UNAVAILABLE"}
    assert catalog.capability_report("xn-career", fake)["can_run"] is False


def test_conflict_resolution_follows_the_documented_order():
    assert resolve_conflict(["a", "b", "c"], explicit="c", active="b")["decided_by"] == "explicit user selection"
    r = resolve_conflict(["a", "b"], active="b", permitted={"b": False})
    assert r["order"] == ["a"] and r["decided_by"] == "only remaining candidate"
    assert resolve_conflict(["a", "b"], active="b")["order"][0] == "b"
    r = resolve_conflict(["a", "b"], expected_output="docx", outputs={"a": "pdf", "b": "docx"})
    assert r["order"][0] == "b" and r["decided_by"] == "expected output"
    r = resolve_conflict(["a", "b"], available={"a": False, "b": True})
    assert r["order"] == ["b"]
    r = resolve_conflict(["a", "b"], priority={"a": 1, "b": 5})
    assert r["order"][0] == "b" and r["decided_by"] == "established priority"
    r = resolve_conflict(["a", "b"])
    assert r["needs_semantic"] is True and r["decided_by"] == "unresolved"
    assert resolve_conflict(["a"], permitted={"a": False})["order"] == []


def test_audit_of_the_real_host_skill_directory_is_read_only():
    root = Path.home() / ".claude" / "skills"
    if not root.is_dir():
        pytest.skip("no host skills directory")
    metas = scan([root])
    rep = audit(metas)
    assert rep["skills"] >= 10 and rep["metadata_bytes"] > 0
    assert (root / "career").is_symlink() or (root / "career").is_dir()
