from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .spec import DomainSpec

FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
REQ = re.compile(r"^Required capabilities:\s*(.+)$", re.M)
OPT = re.compile(r"^Optional capabilities:\s*(.+)$", re.M)
CAP_ID = re.compile(r"\b[a-z]+(?:\.[a-z_]+)+\b")
TOOL_NAME = re.compile(r"\bmcp__[a-z0-9_\-]+__[a-z0-9_]+\b")


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONT.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^[A-Za-z_][\w\-]*:", line):
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip().strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    body_bytes: int
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    hardcoded_tools: int = 0

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def metadata_bytes(self) -> int:
        return len(self.name) + len(self.description)


def _caps(line: str | None) -> tuple[str, ...]:
    return tuple(CAP_ID.findall(line)) if line else ()


def read_meta(skill_md: Path) -> SkillMeta | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = parse_frontmatter(text)
    if not fm.get("name"):
        return None
    body = FRONT.sub("", text, count=1)
    req, opt = REQ.search(body), OPT.search(body)
    refs = tuple(sorted(str(p.relative_to(skill_md.parent)) for p in (skill_md.parent / "references").glob("*.md"))) if (skill_md.parent / "references").is_dir() else ()
    return SkillMeta(
        name=fm["name"], description=fm.get("description", ""), path=skill_md, body_bytes=len(body.encode()),
        required=_caps(req.group(1) if req else None), optional=_caps(opt.group(1) if opt else None), references=refs,
        hardcoded_tools=len(TOOL_NAME.findall(body)),
    )


def scan(roots: list[Path]) -> list[SkillMeta]:
    metas: dict[str, SkillMeta] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            md = entry / "SKILL.md"
            if md.is_file():
                meta = read_meta(md)
                if meta and meta.name not in metas:
                    metas[meta.name] = meta
    return list(metas.values())


@dataclass
class SkillCatalog:
    skills: dict[str, SkillMeta] = field(default_factory=dict)

    @classmethod
    def from_roots(cls, roots: list[Path]) -> "SkillCatalog":
        return cls({m.name: m for m in scan(roots)})

    def metadata_bytes(self) -> int:
        return sum(m.metadata_bytes for m in self.skills.values())

    def plan_load(self, skill: str, stage_references: tuple[str, ...], *, active: bool = False) -> dict[str, Any]:
        meta = self.skills[skill]
        load: list[str] = []
        loaded_bytes = 0
        if not active:
            load.append("SKILL.md")
            loaded_bytes += meta.body_bytes
        for ref in stage_references:
            target = (meta.dir / ref).resolve()
            if meta.dir.resolve() not in target.parents or not target.is_file():
                raise FileNotFoundError(f"reference '{ref}' of skill '{skill}' is missing or escapes the skill directory")
            load.append(ref)
            loaded_bytes += target.stat().st_size
        skipped = [r for r in meta.references if r not in stage_references]
        eager = meta.body_bytes + sum((meta.dir / r).stat().st_size for r in meta.references)
        return {"load": load, "skipped": skipped, "bytes_loaded": loaded_bytes, "bytes_if_eager": eager}

    def capability_report(self, skill: str, resolver) -> dict[str, Any]:
        meta = self.skills[skill]
        report: dict[str, Any] = {}
        for cap in meta.required + meta.optional:
            try:
                res = resolver(cap)
            except Exception as e:
                report[cap] = {"status": "UNKNOWN_CAPABILITY", "required": cap in meta.required, "error": type(e).__name__}
                continue
            report[cap] = {"status": res["status"], "required": cap in meta.required, "degraded": res.get("degraded_behavior")}
        blocking = [c for c, r in report.items() if r["required"] and r["status"] in ("UNAVAILABLE", "UNKNOWN_CAPABILITY")]
        degraded = [c for c, r in report.items() if r["status"] == "DEGRADED"]
        return {"capabilities": report, "blocking": blocking, "degraded": degraded, "can_run": not blocking}

    def validate(self, skill: str, spec: DomainSpec, known_capabilities: set[str]) -> list[str]:
        meta = self.skills[skill]
        issues: list[str] = []
        if not meta.description or len(meta.description) > 420:
            issues.append("description must be present and at most 420 characters")
        if meta.hardcoded_tools:
            issues.append(f"{meta.hardcoded_tools} hardcoded mcp__ tool name(s); depend on capabilities instead")
        declared = set(meta.required) | set(meta.optional)
        for cap in sorted(declared - known_capabilities):
            issues.append(f"declares unknown capability '{cap}'")
        needed = {c for st in spec.stages for c in st.capabilities}
        for cap in sorted(needed - set(meta.required)):
            issues.append(f"domain stage needs '{cap}' but the skill does not list it as required")
        opt_needed = {c for st in spec.stages for c in st.optional_capabilities}
        for cap in sorted(opt_needed - declared):
            issues.append(f"domain stage lists optional '{cap}' that the skill does not mention")
        for st in spec.stages:
            for ref in st.references:
                if not (meta.dir / ref).is_file():
                    issues.append(f"stage '{st.name}' references missing file {ref}")
        return issues


def resolve_conflict(
    candidates: list[str],
    *,
    explicit: str | None = None,
    active: str | None = None,
    expected_output: str | None = None,
    outputs: dict[str, str] | None = None,
    available: dict[str, bool] | None = None,
    permitted: dict[str, bool] | None = None,
    priority: dict[str, int] | None = None,
) -> dict[str, Any]:
    pool = list(dict.fromkeys(candidates))
    trace: list[str] = []
    if explicit and explicit in pool:
        return {"order": [explicit] + [c for c in pool if c != explicit], "decided_by": "explicit user selection", "needs_semantic": False, "trace": ["explicit"]}
    if permitted:
        denied = [c for c in pool if permitted.get(c) is False]
        if denied:
            trace.append(f"dropped for permission: {denied}")
            pool = [c for c in pool if c not in denied]
    if available:
        gone = [c for c in pool if available.get(c) is False]
        if gone:
            trace.append(f"dropped for missing capabilities: {gone}")
            pool = [c for c in pool if c not in gone]
    if not pool:
        return {"order": [], "decided_by": "none left", "needs_semantic": False, "trace": trace}
    if active and active in pool:
        return {"order": [active] + [c for c in pool if c != active], "decided_by": "active workflow context", "needs_semantic": False, "trace": trace + ["active"]}
    if expected_output and outputs:
        fit = [c for c in pool if outputs.get(c) == expected_output]
        if len(fit) == 1:
            return {"order": fit + [c for c in pool if c not in fit], "decided_by": "expected output", "needs_semantic": False, "trace": trace + ["output"]}
        if fit:
            pool = fit + [c for c in pool if c not in fit]
    if priority:
        ranked = sorted(pool, key=lambda c: (-priority.get(c, 0), pool.index(c)))
        if len(ranked) > 1 and priority.get(ranked[0], 0) > priority.get(ranked[1], 0):
            return {"order": ranked, "decided_by": "established priority", "needs_semantic": False, "trace": trace + ["priority"]}
    if len(pool) == 1:
        return {"order": pool, "decided_by": "only remaining candidate", "needs_semantic": False, "trace": trace}
    return {"order": pool, "decided_by": "unresolved", "needs_semantic": True, "trace": trace + ["host model must disambiguate"]}


def audit(metas: list[SkillMeta]) -> dict[str, Any]:
    def toks(text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z]{4,}", text.lower())}

    sets = {m.name: toks(m.description) for m in metas}
    names = sorted(sets)
    overlaps = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            inter = len(sets[a] & sets[b])
            union = len(sets[a] | sets[b])
            if union and inter / union >= 0.5 and inter >= 6:
                overlaps.append({"a": a, "b": b, "jaccard": round(inter / union, 2)})
    overlaps.sort(key=lambda o: -o["jaccard"])
    return {
        "skills": len(metas),
        "metadata_bytes": sum(m.metadata_bytes for m in metas),
        "metadata_tokens_est": sum(m.metadata_bytes for m in metas) // 4,
        "body_bytes_total": sum(m.body_bytes for m in metas),
        "oversized_bodies": sorted(((m.name, m.body_bytes) for m in metas if m.body_bytes > 20_000), key=lambda t: -t[1])[:10],
        "with_references": sum(1 for m in metas if m.references),
        "hardcoded_tool_names": sum(m.hardcoded_tools for m in metas),
        "skills_with_hardcoded_tool_names": sorted(m.name for m in metas if m.hardcoded_tools)[:20],
        "no_description": sorted(m.name for m in metas if not m.description),
        "overlapping_pairs": overlaps[:15],
    }
