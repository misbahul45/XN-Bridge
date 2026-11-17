from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ... import entities
from ...errors import NotFound, PolicyDenied, ValidationFailed
from ...security import check_read_path, digest_obj, redact
from ...spec import Ctx
from .model import ProfileConfirm, ProfileIngest

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",), "java": ("java",), "javascript": ("javascript", "js", "ecmascript"), "typescript": ("typescript", "ts"),
    "golang": ("golang",), "c++": (r"c\+\+",), "c#": (r"c#",), "php": ("php",), "ruby": ("ruby",), "rust": ("rust",), "kotlin": ("kotlin",),
    "swift": ("swift",), "dart": ("dart",), "flutter": ("flutter",), "react": ("react", "reactjs", r"react\.js"), "react native": ("react native",),
    "next.js": (r"next\.js", "nextjs"), "vue": ("vue", r"vue\.js", "vuejs"), "angular": ("angular",), "svelte": ("svelte",),
    "node.js": (r"node\.js", "nodejs", "node"), "express": ("express", r"express\.js"), "nestjs": ("nestjs", r"nest\.js"), "django": ("django",),
    "flask": ("flask",), "fastapi": ("fastapi",), "spring boot": ("spring boot", "springboot"), "laravel": ("laravel",), "tailwind": ("tailwind", "tailwindcss"),
    "html": ("html", "html5"), "css": ("css", "css3"), "sql": ("sql",), "postgresql": ("postgresql", "postgres"), "mysql": ("mysql",), "mongodb": ("mongodb", "mongo"),
    "redis": ("redis",), "sqlite": ("sqlite",), "docker": ("docker",), "kubernetes": ("kubernetes", "k8s"), "git": ("git",), "github actions": ("github actions",),
    "ci/cd": (r"ci/cd", "cicd"), "linux": ("linux", "ubuntu"), "aws": ("aws", "amazon web services"), "gcp": ("gcp", "google cloud"), "azure": ("azure",),
    "terraform": ("terraform",), "graphql": ("graphql",), "rest api": ("rest api", "restful", "rest apis"), "grpc": ("grpc",), "pandas": ("pandas",), "numpy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn"), "tensorflow": ("tensorflow",), "pytorch": ("pytorch", "torch"), "keras": ("keras",), "opencv": ("opencv",),
    "nlp": ("nlp", "natural language processing"), "machine learning": ("machine learning", "ml"), "deep learning": ("deep learning",),
    "computer vision": ("computer vision",), "data analysis": ("data analysis", "data analytics"), "tableau": ("tableau",), "power bi": ("power bi", "powerbi"),
    "excel": ("excel",), "figma": ("figma",), "ui/ux": (r"ui/ux", "ux design", "ui design"), "jira": ("jira",), "agile": ("agile", "scrum"),
    "firebase": ("firebase",), "supabase": ("supabase",), "prisma": ("prisma",), "kafka": ("kafka",), "rabbitmq": ("rabbitmq",),
    "elasticsearch": ("elasticsearch",), "airflow": ("airflow",), "spark": ("spark", "pyspark"), "langchain": ("langchain",), "llm": ("llm", "llms"),
    "rag": ("rag",), "selenium": ("selenium",), "playwright": ("playwright",), "jest": ("jest",), "pytest": ("pytest",), "cypress": ("cypress",),
    "postman": ("postman",), "openapi": ("openapi", "swagger"), "android": ("android",), "ios": ("ios",), "unity": ("unity",), "arduino": ("arduino",),
    "raspberry pi": ("raspberry pi",), "iot": ("iot",), "matlab": ("matlab",), "latex": ("latex",), "bash": ("bash", "shell scripting"),
    "mcp": ("mcp", "model context protocol"), "cybersecurity": ("cybersecurity", "cyber security", "penetration testing"),
}
_SKILL_RE = {
    canon: re.compile(r"(?<![A-Za-z0-9+#.])(?:" + "|".join(aliases) + r")(?![A-Za-z0-9+#]|\.[A-Za-z0-9])", re.I)
    for canon, aliases in SKILL_ALIASES.items()
}
SECTION_WORDS: dict[str, tuple[str, ...]] = {
    "education": ("education", "pendidikan", "riwayat pendidikan", "academic background", "academic"),
    "experience": ("experience", "work experience", "pengalaman", "pengalaman kerja", "employment", "work history", "professional experience", "internship"),
    "projects": ("projects", "project", "proyek", "personal projects", "portfolio", "selected projects"),
    "skills": ("skills", "keahlian", "kemampuan", "technical skills", "competencies", "tools", "technologies", "tech stack", "skill"),
    "languages": ("languages", "bahasa", "language"),
    "certifications": ("certifications", "sertifikasi", "certificates", "courses", "pelatihan", "training"),
    "summary": ("summary", "profile", "about", "about me", "ringkasan", "tentang saya", "objective"),
    "awards": ("awards", "achievements", "prestasi", "penghargaan", "honors"),
    "activities": ("organization", "organisasi", "volunteer", "leadership", "kepanitiaan", "activities", "extracurricular"),
}
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*#*\s*$")
_HEADING_BOLD = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
_HEADING_CAPS = re.compile(r"^\s*([A-Z][A-Z &/]{3,40})\s*:?\s*$")
_HEADING_COLON = re.compile(r"^\s*([A-Za-z][A-Za-z &/]{2,38}):\s*$")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦·]|\d+[.)])\s+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)\d{3,4}[\s\-]?\d{3,5}(?!\d)")
DEGREE_RE = re.compile(r"\b(bachelor|b\.?sc\.?|b\.?eng|s1|sarjana|master|m\.?sc\.?|s2|magister|diploma|d[134]|d-?iii|d-?iv|smk|sma|high school|undergraduate|b\.?tech)\b", re.I)
GRAD_RE = re.compile(r"(?:expected|graduat\w*|lulus|wisuda|class of|est\.?)[^\n\d]{0,30}((?:19|20)\d{2})", re.I)
GPA_RE = re.compile(r"\b(?:gpa|ipk)\s*[:=]?\s*([0-4][.,]\d{1,2})(?:\s*/\s*4(?:[.,]0+)?)?", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
DATE_RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*[-–—to]+\s*((?:19|20)\d{2}|present|now|sekarang|sekarang)", re.I)


def find_skills(text: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for i, line in enumerate(text.splitlines(), 1):
        for canon, rx in _SKILL_RE.items():
            if rx.search(line):
                found.setdefault(canon, []).append(i)
    return found


def _section_for(heading: str) -> str | None:
    h = re.sub(r"[^a-z ]+", " ", heading.lower()).strip()
    for section, words in SECTION_WORDS.items():
        if h in words or any(h.startswith(w + " ") or h.endswith(" " + w) for w in words):
            return section
    return None


def _heading_text(line: str) -> str | None:
    for rx in (_HEADING_MD, _HEADING_BOLD, _HEADING_CAPS, _HEADING_COLON):
        m = rx.match(line)
        if m:
            return m.group(1).strip()
    return None


def split_sections(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    sections: dict[str, list[tuple[int, str]]] = {"_preamble": []}
    current = "_preamble"
    for i, raw in enumerate(lines, 1):
        h = _heading_text(raw)
        sec = _section_for(h) if h else None
        if sec:
            current = sec
            sections.setdefault(current, [])
            continue
        if raw.strip():
            sections.setdefault(current, []).append((i, raw.rstrip()))
    return sections


def _entries(block: list[tuple[int, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for ln, text in block:
        stripped = _BULLET.sub("", text).strip()
        sub = _heading_text(text)
        new_item = bool(_BULLET.match(text)) or bool(sub) or cur is None
        if new_item:
            cur = {"line": ln, "text": stripped}
            entries.append(cur)
        else:
            cur["text"] += " " + stripped
    return entries


def extract_profile(text: str, label: str) -> dict[str, Any]:
    lines = text.splitlines()
    sections = split_sections(lines)
    skills_all = find_skills(text)
    declared: set[str] = set()
    for ln, t in sections.get("skills", []):
        for canon, rx in _SKILL_RE.items():
            if rx.search(t):
                declared.add(canon)
    skills = [
        {"name": k, "lines": v[:6], "declared": k in declared, "source": f"{label}#L{v[0]}"}
        for k, v in sorted(skills_all.items(), key=lambda kv: (kv[0] not in declared, kv[0]))
    ]
    education = []
    for e in _entries(sections.get("education", [])):
        years = sorted({int(y) for y in YEAR_RE.findall(e["text"])})
        education.append({"text": e["text"][:300], "years": years, "degree": bool(DEGREE_RE.search(e["text"])), "source": f"{label}#L{e['line']}"})
    projects = []
    for e in _entries(sections.get("projects", [])):
        sk = sorted(find_skills(e["text"]).keys())
        projects.append({"text": e["text"][:500], "skills": sk, "source": f"{label}#L{e['line']}"})
    experience = [
        {"text": e["text"][:500], "dates": [list(m) for m in DATE_RANGE_RE.findall(e["text"])], "skills": sorted(find_skills(e["text"]).keys()), "source": f"{label}#L{e['line']}"}
        for e in _entries(sections.get("experience", []) + sections.get("activities", []))
    ]
    languages = [{"text": e["text"][:120], "source": f"{label}#L{e['line']}"} for e in _entries(sections.get("languages", []))]
    certs = [{"text": e["text"][:200], "source": f"{label}#L{e['line']}"} for e in _entries(sections.get("certifications", []))]
    emails = sorted(set(EMAIL_RE.findall(text)))
    phones = sorted({re.sub(r"\s+", " ", p).strip() for p in PHONE_RE.findall(text) if len(re.sub(r"\D", "", p)) >= 9})
    grads = sorted({int(m) for m in GRAD_RE.findall(text)})
    gpas = sorted({m.replace(",", ".") for m in GPA_RE.findall(text)})
    conflicts = []
    if len(grads) > 1:
        conflicts.append({"field": "graduation_year", "values": grads, "action": "ask the user which year is correct"})
    if len(gpas) > 1:
        conflicts.append({"field": "gpa", "values": gpas, "action": "ask the user which value is correct"})
    unknown = [k for k, v in (("education", education), ("projects", projects), ("experience", experience), ("languages", languages), ("skills", skills)) if not v]
    unknown += ["graduation_year"] if not grads else []
    unknown += ["availability", "work_authorization", "student_status", "work_preference"]
    return {
        "skills": skills,
        "education": education,
        "projects": projects,
        "experience": experience,
        "languages": languages,
        "certifications": certs,
        "candidates": {"graduation_year": grads, "gpa": gpas},
        "private": {"emails": emails[:3], "phones": phones[:3]},
        "conflicts": conflicts,
        "unknown": unknown,
        "stats": {"lines": len(lines), "chars": len(text)},
    }


def content_digest(data: dict[str, Any]) -> str:
    return digest_obj({k: data[k] for k in ("skills", "education", "projects", "experience", "languages", "certifications")})


def mask_email(e: str) -> str:
    user, _, dom = e.partition("@")
    return (user[:1] + "***@" + dom) if user else "***"


def latest_profile(con, workflow_id: str, profile_id: str | None = None) -> dict[str, Any]:
    if profile_id:
        return entities.get(con, profile_id, workflow_id, "profile")
    head = entities.find(con, workflow_id, "profile_head", "head")
    if head is None:
        raise NotFound("no candidate profile yet; run career.profile.ingest first")
    return entities.get(con, head["data"]["profile_id"], workflow_id, "profile")


def public_view(profile: dict[str, Any]) -> dict[str, Any]:
    d = profile["data"]
    return {
        "profile_id": profile["id"],
        "version": d["version"],
        "skills": [s["name"] for s in d["skills"]][:40],
        "education": len(d["education"]),
        "projects": len(d["projects"]),
        "experience": len(d["experience"]),
        "confirmed": sorted(d.get("confirmed", {})),
        "conflicts": d.get("conflicts", []),
        "unknown": d.get("unknown", []),
        "contact_on_file": {"email": [mask_email(e) for e in d["private"].get("emails", [])], "phone": bool(d["private"].get("phones"))},
    }


def _read_cv_file(path: str) -> tuple[str, dict[str, Any]]:
    p = check_read_path(path, [])
    if not p.is_file():
        raise ValidationFailed("path is not a file")
    if p.suffix.lower() not in (".md", ".txt", ".markdown"):
        raise ValidationFailed("only .md/.txt can be read directly; extract PDF/DOCX with the document.extract capability and pass the text")
    if p.stat().st_size > 2_000_000:
        raise ValidationFailed("file is larger than 2MB")
    data = p.read_bytes()
    return data.decode("utf-8", errors="replace"), {"path": str(p), "file_digest": hashlib.sha256(data).hexdigest(), "bytes": len(data), "mtime": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat()}


def ingest(ctx: Ctx, p: ProfileIngest) -> dict[str, Any]:
    b = ctx.bridge
    file_meta: dict[str, Any] | None = None
    if p.path:
        text, file_meta = _read_cv_file(p.path)
    else:
        text = p.text or ""
    if len(text.strip()) < 40:
        raise ValidationFailed("document text is too short to be a CV")
    label = p.label or (Path(p.path).name if p.path else "cv-text")
    data = extract_profile(text, label)
    digest = digest_obj({"profile": content_digest(data), "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
    if p.evidence_id:
        ev = b.evidence.get(p.evidence_id)
        ok, why = b.evidence.usable_as_verified(p.evidence_id)
        if not ok or ev["origin"] not in ("local_file", "tool_output"):
            raise ValidationFailed(f"CV extraction evidence is unusable: {why}")
        if ev["workflow_id"] != ctx.workflow_id or ev["digest"] != hashlib.sha256(text.encode()).hexdigest():
            raise ValidationFailed("CV extraction evidence must belong to this workflow and match the exact text")
        b.artifacts.read(ev["artifact_id"])
    else:
        ev = b.evidence.register(
            workflow_id=ctx.workflow_id, claim=f"Candidate profile extracted from {label}", origin="local_file" if file_meta else "tool_output",
            requested="VERIFIED" if file_meta else "UNVERIFIED", source_ref=file_meta["path"] if file_meta else None, content=text,
            provider=f"extractor:{p.extractor}", ttl_class="default",
        )
    with b.store.tx() as con:
        head = entities.find(con, ctx.workflow_id, "profile_head", "head")
        prev = entities.get(con, head["data"]["profile_id"], ctx.workflow_id, "profile") if head else None
        if prev and prev["data"]["digest"] == digest:
            return {"summary": {"unchanged": True, **public_view(prev)}}
        version = (prev["data"]["version"] + 1) if prev else 1
        carried = dict(prev["data"].get("confirmed", {})) if prev else {}
        data.update({"version": version, "digest": digest, "confirmed": carried, "source": {"label": label, "file": file_meta, "evidence_id": ev["id"], "extractor": p.extractor}})
        ent, _ = entities.upsert(con, ctx.workflow_id, "profile", f"v{version}", data, status="CURRENT")
        if prev:
            entities.update(con, prev["id"], prev["data"], "SUPERSEDED")
        entities.upsert(con, ctx.workflow_id, "profile_head", "head", {"profile_id": ent["id"]})
        out = public_view(ent)
    out["evidence_id"] = ev["id"]
    return {
        "summary": {"unchanged": False, **out},
        "next": "ask the user to confirm the unknown fields with career.profile.confirm (availability, work_authorization, student_status, graduation_year, work_preference)",
    }


def confirm(ctx: Ctx, p: ProfileConfirm) -> dict[str, Any]:
    b = ctx.bridge
    ev = b.evidence.register(
        workflow_id=ctx.workflow_id, claim="User-confirmed profile facts: " + ", ".join(sorted(p.facts)), origin="user_statement",
        requested="VERIFIED", source_ref="user:chat", excerpt=p.quote, provider="user",
    )
    with b.store.tx() as con:
        prev = latest_profile(con, ctx.workflow_id)
        data = dict(prev["data"])
        confirmed = dict(data.get("confirmed", {}))
        now = datetime.now(UTC).isoformat()
        for k, v in p.facts.items():
            confirmed[k] = {"value": v, "evidence_id": ev["id"], "at": now}
        data["confirmed"] = confirmed
        conflicts = []
        for c in data.get("conflicts", []):
            field = c["field"]
            if field in confirmed and str(confirmed[field]["value"]).replace(",", ".") in {str(x) for x in c["values"]}:
                continue
            conflicts.append(c)
        data["conflicts"] = conflicts
        data["unknown"] = [u for u in data.get("unknown", []) if u not in confirmed]
        version = data["version"] + 1
        data["version"] = version
        ent, _ = entities.upsert(con, ctx.workflow_id, "profile", f"v{version}", data, status="CURRENT")
        entities.update(con, prev["id"], prev["data"], "SUPERSEDED")
        entities.upsert(con, ctx.workflow_id, "profile_head", "head", {"profile_id": ent["id"]})
        view = public_view(ent)
    return {"summary": {**view, "evidence_id": ev["id"]}}
