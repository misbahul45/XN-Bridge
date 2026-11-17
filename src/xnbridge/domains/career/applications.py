from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ... import entities
from ...errors import InvalidTransition, NotFound, PolicyDenied, ValidationFailed
from ...security import digest_obj, origin_of, scan_untrusted
from ...spec import Ctx
from ...textutil import host_of, registrable_domain, tokens
from . import ats as atsmod
from .discovery import current_campaign, get_company, verified_domains
from .matching import hard_checks, tier_of
from .model import ApplicationPrepare, DraftCheck, FormParse, FormPlan, Report, SubmissionPrepare, TrackingUpdate
from .profile import SKILL_ALIASES, find_skills, latest_profile

ASK_RE = re.compile(
    r"authori[sz]ed to work|work authori|legally|\bvisa\b|sponsorship|citizen|nationality|kewarganegaraan|criminal|convicted|disabilit|\bgender\b|jenis kelamin|"
    r"\brace\b|ethnic|veteran|religion|agama|marital|pregnan|date of birth|tanggal lahir|\bbirth|\bssn\b|social security|national id|\bnik\b|\bktp\b|passport|paspor|"
    r"salary|\bgaji\b|expected (pay|compensation)|relocat|background check|consent|\bagree\b|i certify|i declare|i confirm|terms|privacy|data protection|kebijakan privasi|"
    r"persetujuan|saya menyatakan|saya setuju|\breferral\b|\breferred by\b|\breferrer\b|relative|family member|conflict of interest|how did you hear|dari mana",
    re.I,
)
BLOCK_RE = re.compile(
    r"captcha|verify (that )?you('| a)re (not a )?(robot|human)|i'?m not a robot|one[- ]time (password|code)|\botp\b|verification code|two[- ]factor|\b2fa\b|\bpassword\b|kata sandi|sign in|log ?in|\bmasuk\b",
    re.I,
)
SUBMIT_RE = re.compile(r"^(submit|send application|apply( now)?|kirim|lamar|finish|complete application|selesai|send)\b", re.I)
NAV_RE = re.compile(r"^(next|continue|lanjut|berikutnya|selanjutnya|save and continue|back|previous|kembali)\b", re.I)
UPLOAD_RE = re.compile(r"upload|choose file|attach|browse|unggah|pilih file|lampirkan|drop (your )?(cv|resume|file)", re.I)
RULES: tuple[tuple[str, str], ...] = (
    ("full_name", r"\b(full name|nama lengkap|your name|^name\b|^nama\b)"),
    ("email", r"e-?mail|surel"),
    ("phone", r"phone|telepon|telp|whatsapp|no\.? ?hp|mobile|nomor"),
    ("gpa", r"\bgpa\b|\bipk\b|grade point"),
    ("graduation_year", r"graduat|lulus|wisuda"),
    ("location", r"\bcity\b|\bkota\b|location|domicile|domisili|address|alamat"),
    ("github", r"github"),
    ("linkedin", r"linkedin"),
    ("portfolio", r"portfolio|website|personal site|\burl\b"),
    ("university", r"university|universitas|college|institution|kampus|school|institusi"),
    ("major", r"\bmajor\b|jurusan|program studi|field of study|prodi"),
    ("availability", r"start date|available from|tanggal mulai|mulai magang|availability|ketersediaan|duration|durasi"),
    ("draft", r"cover letter|motivation|surat lamaran|why |motivasi|alasan|tell us about|ceritakan|describe|additional information|anything else|message|pesan"),
)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PREPARED": {"AWAITING_APPROVAL", "WITHDRAWN"},
    "AWAITING_APPROVAL": {"PREPARED", "SUBMITTED", "OUTCOME_UNKNOWN", "WITHDRAWN"},
    "SUBMITTED": {"ACKNOWLEDGED", "UNDER_REVIEW", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "OUTCOME_UNKNOWN"},
    "ACKNOWLEDGED": {"UNDER_REVIEW", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN"},
    "UNDER_REVIEW": {"INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN"},
    "INTERVIEW": {"ACCEPTED", "REJECTED", "WITHDRAWN"},
    "OUTCOME_UNKNOWN": {"SUBMITTED", "PREPARED", "WITHDRAWN"},
    "ACCEPTED": set(),
    "REJECTED": set(),
    "WITHDRAWN": set(),
}
EVIDENCE_REQUIRED = {"ACKNOWLEDGED", "UNDER_REVIEW", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN"}
STOP_ENTITIES = {"CV", "PKL", "GPA", "IPK", "IT", "AI", "ML", "PDF", "HR", "API", "SQL", "UI", "UX", "REST", "HTML", "CSS", "I"}


def _norm(profile: dict[str, Any], key: str) -> Any:
    c = profile["data"].get("confirmed", {}).get(key)
    return c["value"] if c else None


def fact_pack(profile: dict[str, Any]) -> dict[str, Any]:
    d = profile["data"]
    skills = [s["name"] for s in d["skills"] if s["declared"]][:15] or [s["name"] for s in d["skills"]][:15]
    return {
        "skills": skills,
        "education": [e["text"][:200] for e in d["education"][:2]],
        "projects": [p["text"][:240] for p in d["projects"][:3]],
        "experience": [e["text"][:240] for e in d["experience"][:3]],
        "confirmed": {k: ("<on file>" if k in ("contact", "full_name") else v["value"]) for k, v in d.get("confirmed", {}).items()},
        "rule": "use only these facts; anything else must be asked from the user, never invented",
    }


def _skeleton(profile: dict[str, Any], opp: dict[str, Any], company: dict[str, Any]) -> dict[str, str]:
    d = profile["data"]
    name = _norm(profile, "full_name") or "[candidate name to be confirmed]"
    edu = d["education"][0]["text"] if d["education"] else "[education to be confirmed]"
    skills = ", ".join(s["name"] for s in d["skills"])[:300] if d["skills"] else "[skills to be confirmed]"
    proj = d["projects"][0]["text"][:260] if d["projects"] else "[project to be added by the candidate]"
    avail = _norm(profile, "availability")
    avail_txt = f"My confirmed availability: {avail}." if avail else "[availability to be confirmed by the candidate]"
    title, cname = opp["data"]["title"], company["data"]["name"]
    letter = (
        f"Dear {cname} hiring team,\n\nI am applying for the {title} position. {edu}\n\n"
        f"Skills listed on my CV: {skills}.\n\nA project from my CV: {proj}\n\n{avail_txt}\n\nThank you for your time and consideration.\n\n{name}\n"
    )
    short = f"Hello {cname} team, I would like to apply for {title}. My CV lists: {skills}. {avail_txt}"
    return {"cover_letter": letter, "short_message": short}


def prepare(ctx: Ctx, p: ApplicationPrepare) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.tx() as con:
        opp = entities.get(con, p.opportunity_id, ctx.workflow_id, "opportunity")
        if opp["status"] in ("EXPIRED", "UNKNOWN"):
            raise PolicyDenied(f"opportunity is {opp['status']} and cannot be applied to", details={"reasons": opp["data"].get("status_reasons", [])})
        if opp["data"].get("flags"):
            raise PolicyDenied("the posting text contains instruction-like patterns; a human must review it before any application", details={"flags": opp["data"]["flags"]})
        profile = latest_profile(con, ctx.workflow_id)
        company = get_company(con, ctx.workflow_id, opp["data"]["company_id"])
        campaign = current_campaign(con, ctx.workflow_id)
        checks = hard_checks(profile, opp, campaign)
        tier = tier_of(checks)
        if tier == "INELIGIBLE":
            raise PolicyDenied("candidate fails hard requirements for this opportunity", details={"failed": [c for c in checks if c["result"] == "FAIL"]})
        if tier == "UNKNOWN_ELIGIBILITY" and not p.acknowledge_unknown_eligibility:
            raise PolicyDenied(
                "eligibility is UNKNOWN for some hard requirements; confirm those facts or acknowledge the risk explicitly",
                details={"unknown": [c for c in checks if c["result"] == "UNKNOWN"]},
            )
        if p.channel == "EMAIL" and opp["status"] != "INQUIRY_ONLY" and not opp["data"].get("apply_url"):
            raise PolicyDenied("no verified recipient route for an email application")
        key = f"{profile['id']}|{opp['id']}|{p.channel}"
        existing = entities.find(con, ctx.workflow_id, "application", key)
        if existing:
            data = existing["data"]
            stale = data["profile_version"] != profile["data"]["version"]
            return {"summary": {"application_id": existing["id"], "created": False, "status": existing["status"], "profile_stale": stale, "needs_confirmation": data["needs_confirmation"]}}
        drafts = _skeleton(profile, opp, company)
        refs = {}
        for name, text in drafts.items():
            art = b.artifacts.put(ctx.workflow_id, "draft", text, "text/markdown", con=con)
            refs[name] = {"artifact_id": art["id"], "digest": art["digest"]}
        needs = []
        for k in ("full_name", "contact", "availability"):
            if _norm(profile, k) is None:
                needs.append(k)
        needs += [f"resolve conflict: {c['field']} {c['values']}" for c in profile["data"].get("conflicts", [])]
        needs += [f"confirm: {c['check']}" for c in checks if c["result"] == "UNKNOWN"]
        pack = fact_pack(profile)
        data = {
            "opportunity_id": opp["id"], "company_id": company["id"], "profile_id": profile["id"], "profile_version": profile["data"]["version"], "channel": p.channel,
            "eligibility_tier": tier, "needs_confirmation": needs, "drafts": refs, "draft_checks": {}, "fact_pack_digest": digest_obj(pack),
            "history": [{"status": "PREPARED", "at": datetime.now(UTC).isoformat(), "evidence_id": None, "note": "prepared"}],
        }
        ent, _ = entities.upsert(con, ctx.workflow_id, "application", key, data, status="PREPARED")
    resolve = b.registry.resolve("document.generate")
    return {
        "summary": {"application_id": ent["id"], "created": True, "status": "PREPARED", "eligibility_tier": tier, "drafts": sorted(refs), "needs_confirmation": needs, "document_provider": resolve["status"]},
        "detail": {"fact_pack": pack, "draft_artifacts": refs, "document_generate": resolve.get("selected") or resolve.get("degraded_behavior")},
        "next": "improve the drafts using only the fact pack, run career.draft.check, then career.form.plan; unresolved needs_confirmation items must be asked from the user",
    }


COMMON_WORDS = {
    "Dear", "Hello", "Hi", "Thank", "Thanks", "Regards", "Sincerely", "Best", "Kind", "Yours", "Respectfully", "English", "Indonesian",
    "Indonesia", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Subject", "Team", "Hiring",
}
_CAP_WORD = re.compile(r"[A-Z][A-Za-z0-9&\-]+|[A-Z]{3,}")
_SENTENCE_START = re.compile(r"(?:^|[.!?:]\s+|\n\s*)$")


def _cap_words(text: str, skip_sentence_start: bool) -> set[str]:
    found: set[str] = set()
    for m in _CAP_WORD.finditer(text):
        word = m.group(0)
        if word in STOP_ENTITIES or word in COMMON_WORDS:
            continue
        if skip_sentence_start and _SENTENCE_START.search(text[: m.start()]):
            continue
        found.add(word)
    return found


def check_draft(ctx: Ctx, p: DraftCheck) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.tx() as con:
        app = entities.get(con, p.application_id, ctx.workflow_id, "application")
        profile = entities.get(con, app["data"]["profile_id"], ctx.workflow_id, "profile")
        opp = entities.get(con, app["data"]["opportunity_id"], ctx.workflow_id, "opportunity")
        company = get_company(con, ctx.workflow_id, app["data"]["company_id"])
        pd = profile["data"]
        corpus = " ".join([e["text"] for e in pd["education"]] + [x["text"] for x in pd["projects"]] + [x["text"] for x in pd["experience"]] + [x["text"] for x in pd["languages"]] + [c["text"] for c in pd["certifications"]])
        corpus += " " + " ".join(str(v["value"]) for v in pd.get("confirmed", {}).values())
        corpus += " " + opp["data"]["title"] + " " + opp["data"].get("description", "")[:2000] + " " + company["data"]["name"] + " " + " ".join(company["data"]["aliases"])
        allowed_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", corpus))
        allowed_entities = _cap_words(corpus, False)
        profile_skills = {s["name"] for s in pd["skills"]}
        results: dict[str, Any] = {}
        for name, text in p.texts.items():
            visible = re.sub(r"\[[^\]]+\]", " ", text)
            flagged: list[dict[str, str]] = []
            for num in set(re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(?:\+\s*)?(?:(?:years?|tahun|percent|persen|projects?|proyek|users?|pengguna)\b|%)", visible, re.I)):
                if num not in allowed_numbers:
                    flagged.append({"type": "UNSUPPORTED_NUMBER", "value": num})
            for g in set(re.findall(r"\b(?:gpa|ipk)\b[^\d\n]{0,14}(\d(?:[.,]\d+)?)", visible, re.I)):
                if g not in allowed_numbers:
                    flagged.append({"type": "UNSUPPORTED_GPA", "value": g})
            for sk in sorted(find_skills(visible)):
                if sk not in profile_skills:
                    flagged.append({"type": "SKILL_NOT_ON_CV", "value": sk})
            for ent in sorted(_cap_words(visible, True) - allowed_entities):
                flagged.append({"type": "UNVERIFIED_ENTITY", "value": ent})
            for flag in scan_untrusted(visible):
                flagged.append({"type": "INSTRUCTION_PATTERN", "value": flag})
            verdict = "PASS" if not flagged else "REVIEW"
            art = b.artifacts.put(ctx.workflow_id, "draft_checked", text, "text/markdown", con=con)
            results[name] = {"verdict": verdict, "flagged": flagged[:12], "digest": art["digest"], "artifact_id": art["id"]}
        data = app["data"]
        data["draft_checks"].update({k: {"verdict": v["verdict"], "digest": v["digest"], "artifact_id": v["artifact_id"]} for k, v in results.items()})
        entities.update(con, app["id"], data)
    overall = "PASS" if all(v["verdict"] == "PASS" for v in results.values()) else "REVIEW"
    return {
        "summary": {"application_id": p.application_id, "verdict": overall, "texts": {k: v["verdict"] for k, v in results.items()}},
        "detail": {"results": results},
        "next": "REVIEW items are claims not supported by the CV or listing: remove them or get the user to confirm the fact first" if overall == "REVIEW" else "texts are consistent with the CV facts",
    }


_LINE = re.compile(r'^(?P<indent>\s*)-\s*(?P<role>[A-Za-z]+)(?:\s+"(?P<label>(?:[^"\\]|\\.)*)")?(?P<attrs>(?:\s*\[[^\]]*\])*)\s*(?::\s*(?P<val>.*))?$')
FIELD_ROLES = {"textbox", "searchbox", "combobox", "listbox", "radio", "checkbox", "switch", "spinbutton", "slider", "button"}


def _unquote(raw: str) -> str:
    body = raw.lstrip()
    if body.startswith("- '") and body.rstrip().endswith("'"):
        inner = body.rstrip()[3:-1].replace("''", "'")
        return raw[: len(raw) - len(body)] + "- " + inner
    return raw


def parse_snapshot(text: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    group_label = ""
    group_indent = -1
    group_field: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    current_indent = -1
    step = 1
    for raw in text.splitlines():
        m = _LINE.match(_unquote(raw))
        if not m:
            continue
        indent = len(m.group("indent"))
        role = m.group("role").lower()
        label = (m.group("label") or "").replace('\\"', '"').strip()
        attrs = m.group("attrs") or ""
        ref = re.search(r"\[ref=([^\]]+)\]", attrs)
        if role in ("group", "radiogroup", "fieldset") and label:
            group_label, group_indent, group_field = label, indent, None
            continue
        if group_indent >= 0 and indent <= group_indent:
            group_label, group_indent, group_field = "", -1, None
        if role == "option" and current is not None and indent > current_indent:
            if label:
                current["options"].append(label)
            continue
        if role == "heading" and re.search(r"(step|langkah)\s*(\d+)", label, re.I):
            step = int(re.search(r"(\d+)", label).group(1))
            continue
        if role not in FIELD_ROLES:
            continue
        if role in ("radio", "checkbox") and group_label:
            if group_field is None:
                group_required = "*" in group_label or bool(re.search(r"\brequired\b|wajib", group_label, re.I))
                group_field = {"ref": ref.group(1) if ref else None, "role": f"{role}group", "label": re.sub(r"\s*\*+\s*$", "", group_label).strip()[:300], "required": group_required, "options": [], "step": step, "disabled": False}
                fields.append(group_field)
            group_field["options"].append(label)
            continue
        required = "*" in label or bool(re.search(r"\brequired\b|wajib", label + attrs, re.I))
        clean = re.sub(r"\s*\*+\s*$", "", label).strip()
        kind = role
        if role == "button" and UPLOAD_RE.search(clean):
            kind = "file"
        fields.append({"ref": ref.group(1) if ref else None, "role": kind, "label": clean[:300], "required": required, "options": [], "step": step, "disabled": "disabled" in attrs})
        current, current_indent = fields[-1], indent
    return fields


def _classify_field(f: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    label, role = f["label"], f["role"]
    item = {"ref": f.get("ref"), "label": label, "role": role, "required": f["required"], "step": f.get("step", 1), "conditional": bool(f.get("depends_on"))}
    if f.get("depends_on"):
        item["activate_when"] = f["depends_on"]
    if role == "button":
        if SUBMIT_RE.search(label):
            return {**item, "action": "SUBMIT_BUTTON", "reason": "final submission is a separate EXTERNAL_WRITE action: a human-granted approval, or the owner's unattended mode"}
        if NAV_RE.search(label):
            return {**item, "action": "NAVIGATE", "reason": "multi-step navigation; may autosave"}
        return {**item, "action": "SKIP_OPTIONAL", "reason": "not a data field"}
    if BLOCK_RE.search(label):
        return {**item, "action": "BLOCKED", "reason": "authentication/CAPTCHA/OTP must be done by the user"}
    if role == "file":
        low = label.lower()
        doc = "cv" if re.search(r"cv|resume|curriculum", low) else ("cover_letter" if re.search(r"cover|motivation|letter|surat", low) else ("transcript" if re.search(r"transcript|transkrip", low) else "other"))
        return {**item, "action": "UPLOAD" if doc in ("cv", "cover_letter") else "ASK_USER", "document": doc, "reason": "attach only a user-approved file with a recorded digest"}
    if ASK_RE.search(label):
        return {**item, "action": "ASK_USER", "declaration": True, "reason": "legal, identity, consent or eligibility answer must come from the user"}
    for key, pat in RULES:
        if re.search(pat, label, re.I):
            if key == "draft":
                return {**item, "action": "DRAFT_TEXT", "fact": key, "reason": "free text: draft from the fact pack, then career.draft.check"}
            conf = _norm(profile, key if key != "email" and key != "phone" else "contact")
            if key in ("email", "phone"):
                conf = (conf or {}).get(key) if isinstance(conf, dict) else None
            if key == "availability":
                conf = _norm(profile, "availability")
            if conf is not None:
                return {**item, "action": "FILL", "fact": key, "source": "CONFIRMED", "reason": "confirmed by the user"}
            if key in ("university", "major"):
                return {**item, "action": "CONFIRM_THEN_FILL", "fact": key, "source": "CV_EXTRACTED", "reason": "from the CV; user confirms before use"}
            if key in ("gpa", "graduation_year") and len(profile["data"].get("candidates", {}).get(key, [])) == 1:
                return {**item, "action": "CONFIRM_THEN_FILL", "fact": key, "source": "CV_EXTRACTED", "reason": "single value on the CV; user confirms before use"}
            return {**item, "action": "ASK_USER", "fact": key, "reason": "fact not confirmed yet"}
    if not f["required"]:
        return {**item, "action": "SKIP_OPTIONAL", "reason": "optional and no matching fact"}
    return {**item, "action": "ASK_USER", "reason": "required field with no matching fact"}


def parse_form(ctx: Ctx, p: FormParse) -> dict[str, Any]:
    text = p.text if p.text is not None else ctx.bridge.artifacts.read_text(p.artifact_id, 400_000)
    fields = parse_snapshot(text)
    multi = any(NAV_RE.search(f["label"]) and f["role"] == "button" for f in fields)
    return {
        "summary": {"field_count": len(fields), "required": sum(1 for f in fields if f["required"]), "uploads": sum(1 for f in fields if f["role"] == "file"), "multi_step": multi},
        "detail": {"fields": fields},
        "next": "pass the fields to career.form.plan; do not click anything that submits",
    }


def plan_form(ctx: Ctx, p: FormPlan) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.tx() as con:
        app = entities.get(con, p.application_id, ctx.workflow_id, "application")
        profile = entities.get(con, app["data"]["profile_id"], ctx.workflow_id, "profile")
        items = [_classify_field(f.model_dump(), profile) for f in p.fields]
        counts: dict[str, int] = {}
        for it in items:
            counts[it["action"]] = counts.get(it["action"], 0) + 1
        declarations = [{"label": it["label"], "ref": it.get("ref")} for it in items if it["action"] == "ASK_USER" and it.get("declaration")]
        digest = digest_obj([{k: v for k, v in it.items() if k != "ref"} for it in items])
        entities.upsert(con, ctx.workflow_id, "form_plan", p.application_id, {"digest": digest, "items": items, "declarations": declarations}, status="PLANNED")
    blockers = [it["label"] for it in items if it["action"] == "BLOCKED"]
    return {
        "summary": {"application_id": p.application_id, "plan_digest": digest, "actions": counts, "declarations_for_user": len(declarations), "blocked_by_human_step": blockers},
        "detail": {"items": items, "declarations": declarations},
        "next": "fill only FILL/DRAFT_TEXT/UPLOAD items; ASK_USER items need the user's own answer; stop at SUBMIT_BUTTON and use career.submission.prepare",
    }


def _file_digest(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _target_ok(target: str, opp: dict[str, Any], company: dict[str, Any]) -> tuple[bool, str]:
    host = host_of(target)
    if not host:
        return False, "target has no host"
    if registrable_domain(host) in verified_domains(company):
        return True, "target is on a verified company domain"
    apply_host = host_of(opp["data"].get("apply_url") or "")
    if host == apply_host:
        return True, "target matches the verified apply URL host"
    known = lambda h: any(h == k or h.endswith("." + k) for k in atsmod.KNOWN_ATS_HOSTS)
    if known(host) and known(apply_host):
        return True, "target and apply URL are on known ATS hosts"
    return False, f"target host {host} is not the company's verified domain or the listing's apply host"


def prepare_submission(ctx: Ctx, p: SubmissionPrepare) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.tx() as con:
        app = entities.get(con, p.application_id, ctx.workflow_id, "application")
        opp = entities.get(con, app["data"]["opportunity_id"], ctx.workflow_id, "opportunity")
        company = get_company(con, ctx.workflow_id, app["data"]["company_id"])
        profile = entities.get(con, app["data"]["profile_id"], ctx.workflow_id, "profile")
        if app["status"] not in ("PREPARED", "AWAITING_APPROVAL"):
            raise PolicyDenied(f"application is {app['status']}; only PREPARED applications can be submitted")
        if opp["status"] != "OPEN_VERIFIED":
            raise PolicyDenied(f"opportunity is {opp['status']}; only OPEN_VERIFIED listings can be submitted", details={"reasons": opp["data"].get("status_reasons", [])})
        ok, why = _target_ok(p.target_url, opp, company)
        if not ok:
            raise PolicyDenied(why)
        origin = origin_of(p.target_url)
        stale = [name for name, t in p.texts.items() if app["data"]["draft_checks"].get(name, {}).get("digest") != hashlib.sha256(t.encode()).hexdigest()]
        unchecked = [name for name in p.texts if name not in app["data"]["draft_checks"]]
        if unchecked or stale:
            raise PolicyDenied("every text must pass career.draft.check with identical content", details={"unchecked": unchecked, "changed_since_check": stale})
        failing = [name for name in p.texts if app["data"]["draft_checks"][name]["verdict"] != "PASS"]
        if failing:
            raise PolicyDenied("draft checks must be PASS before submission", details={"failing": failing})
        plan = entities.find(con, ctx.workflow_id, "form_plan", app["id"])
        required_decl = [d["label"] for d in (plan["data"]["declarations"] if plan else [])]
        given = {d.label: d for d in p.declarations}
        missing = [lab for lab in required_decl if lab not in given or not given[lab].user_confirmed or not given[lab].quote]
        if missing:
            raise PolicyDenied("legal, consent and eligibility declarations need the user's own confirmed answer with a quote", details={"missing": missing})
        if plan and p.form_plan_digest and p.form_plan_digest != plan["data"]["digest"]:
            raise PolicyDenied("form plan changed after it was reviewed")
        blocked = [i["label"] for i in (plan["data"]["items"] if plan else []) if i["action"] == "BLOCKED"]
        if blocked:
            raise PolicyDenied("the form has steps only a human can do (login, CAPTCHA, OTP); finish those manually", details={"blocked": blocked})
        src = (profile["data"].get("source") or {}).get("file")
        if src and src.get("path"):
            now_digest = _file_digest(src["path"])
            if now_digest and now_digest != src["file_digest"]:
                raise PolicyDenied("the CV file changed on disk since it was ingested; re-ingest it before submitting")
        att = []
        for a in p.attachments:
            meta = b.artifacts.meta(a.artifact_id)
            att.append({"name": a.name, "artifact_id": a.artifact_id, "digest": meta["digest"], "bytes": meta["bytes"]})
        texts = {}
        for name, t in p.texts.items():
            ch = app["data"]["draft_checks"][name]
            texts[name] = {"digest": ch["digest"], "artifact_id": ch["artifact_id"]}
        manifest = {
            "company": company["data"]["name"], "position": opp["data"]["title"], "destination": p.target_url, "origin": origin,
            "channel": app["data"]["channel"], "application_id": app["id"], "texts": texts, "attachments": att,
            "declarations": [d.model_dump() for d in p.declarations], "form_plan_digest": plan["data"]["digest"] if plan else None,
            "profile_version": profile["data"]["version"], "opportunity_url": opp["data"]["url"],
            "irreversible": f"Submitting sends the content above to {origin}. It cannot be recalled and may notify the employer.",
        }
        ent, _ = entities.upsert(con, ctx.workflow_id, "submission_manifest", f"{app['id']}|{origin}|{digest_obj(manifest)[:12]}", manifest, status="PENDING")
        data = app["data"]
        data["history"].append({"status": "AWAITING_APPROVAL", "at": datetime.now(UTC).isoformat(), "evidence_id": None, "note": f"manifest {ent['id']}"})
        entities.update(con, app["id"], data, "AWAITING_APPROVAL")
    return {
        "summary": {"manifest_id": ent["id"], "destination": origin, "position": manifest["position"], "company": manifest["company"], "texts": sorted(texts), "attachments": len(att), "declarations": len(p.declarations)},
        "detail": {"manifest": manifest},
        "next": {
            "approval_prepare": {"workflow_id": ctx.workflow_id, "action_kind": "application.submit", "target": p.target_url, "payload_ref": f"entity:{ent['id']}"},
            "then": "the user reviews and runs `xnbridge approve <approval_id>`; only then execution_record op=begin, perform the click once, execution_record op=finish with confirmation evidence. If bridge_status reports unattended_external_writes true, skip approval_prepare and call execution_record op=begin with the target and no approval_id",
        },
    }


def update_tracking(ctx: Ctx, p: TrackingUpdate) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.tx() as con:
        app = entities.get(con, p.application_id, ctx.workflow_id, "application")
        cur = app["status"]
        if p.status == cur:
            return {"summary": {"application_id": app["id"], "status": cur, "unchanged": True}}
        if p.status not in ALLOWED_TRANSITIONS.get(cur, set()):
            raise InvalidTransition(f"application cannot move {cur} -> {p.status}", details={"allowed": sorted(ALLOWED_TRANSITIONS.get(cur, set()))})
        evidence_id = p.evidence_id
        if p.status in EVIDENCE_REQUIRED:
            if not evidence_id:
                raise PolicyDenied(f"status {p.status} needs evidence (an email, a page, or a user statement); statuses are never guessed")
            rec = b.evidence.get(evidence_id, con)
            if rec["verification"] not in ("VERIFIED", "UNVERIFIED") or rec["origin"] == "model_summary":
                raise PolicyDenied("evidence for a status change cannot be a model summary or unknown")
        manifest = None
        for m in entities.listing(con, ctx.workflow_id, "submission_manifest"):
            if m["data"]["application_id"] == app["id"]:
                manifest = m
        if p.status in ("SUBMITTED", "OUTCOME_UNKNOWN", "PREPARED") and cur in ("AWAITING_APPROVAL", "OUTCOME_UNKNOWN"):
            if manifest is None:
                raise PolicyDenied("no submission manifest exists for this application")
            row = con.execute(
                "SELECT state FROM executions WHERE workflow_id=? AND risk='EXTERNAL_WRITE' AND target=? ORDER BY started_at DESC LIMIT 1",
                (ctx.workflow_id, manifest["data"]["destination"]),
            ).fetchone()
            state = row["state"] if row else None
            need = {"SUBMITTED": ("SUCCEEDED", "RECONCILED_SUCCEEDED"), "OUTCOME_UNKNOWN": ("OUTCOME_UNKNOWN", "STARTED"), "PREPARED": ("RECONCILED_FAILED", "FAILED")}[p.status]
            if state not in need:
                raise PolicyDenied(f"status {p.status} needs an execution record in {need}; found {state}", details={"hint": "record the attempt with execution_record first"})
        data = app["data"]
        data["history"].append({"status": p.status, "at": datetime.now(UTC).isoformat(), "evidence_id": evidence_id, "note": p.note})
        entities.update(con, app["id"], data, p.status)
    return {"summary": {"application_id": p.application_id, "from": cur, "status": p.status, "history_len": len(data["history"])}}


def pipeline_report(ctx: Ctx, p: Report) -> dict[str, Any]:
    with ctx.bridge.store.read() as con:
        def by_status(kind: str) -> dict[str, int]:
            return {r["status"] or "NONE": r["n"] for r in con.execute("SELECT status,COUNT(*) n FROM entities WHERE workflow_id=? AND kind=? GROUP BY status", (ctx.workflow_id, kind))}

        out = {k: by_status(k) for k in ("company", "opportunity", "match", "application", "submission_manifest")}
        out["profile_versions"] = con.execute("SELECT COUNT(*) FROM entities WHERE workflow_id=? AND kind='profile'", (ctx.workflow_id,)).fetchone()[0]
    return {"summary": out}
