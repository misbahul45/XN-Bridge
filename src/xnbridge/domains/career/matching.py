from __future__ import annotations

from typing import Any

from ... import entities
from ...spec import Ctx
from ...textutil import tokens
from .discovery import current_campaign
from .model import MatchRun
from .profile import latest_profile

WEIGHTS = {"skills": 40, "projects": 20, "experience": 10, "role": 15, "arrangement": 10, "learning": 5}
LEARNING_TERMS = ("mentor", "mentorship", "learn", "training", "guidance", "bimbingan", "belajar", "pelatihan", "onboarding")
MATCHABLE = ("OPEN_VERIFIED", "LISTED_UNCERTAIN", "INQUIRY_ONLY")


def _confirmed(profile: dict[str, Any], key: str) -> Any:
    c = profile["data"].get("confirmed", {}).get(key)
    return c["value"] if c else None


def _norm_place(s: str) -> set[str]:
    return {t for t in tokens(s) if len(t) > 2}


def hard_checks(profile: dict[str, Any], opp: dict[str, Any], campaign: dict[str, Any] | None) -> list[dict[str, str]]:
    d = opp["data"]
    el = d.get("eligibility", {})
    strict = (campaign or {}).get("data", {}).get("strict", {})
    p_skills = {s["name"] for s in profile["data"]["skills"]}
    checks: list[dict[str, str]] = []

    def add(name: str, result: str, detail: str) -> None:
        checks.append({"check": name, "result": result, "detail": detail})

    auth = _confirmed(profile, "work_authorization")
    needed_auth = el.get("work_authorization")
    if needed_auth:
        if auth is None:
            add("work_authorization", "UNKNOWN", f"listing requires {needed_auth}; candidate has not confirmed work authorization")
        elif any(_norm_place(n) & _norm_place(" ".join(auth)) for n in needed_auth):
            add("work_authorization", "PASS", f"authorized in {auth}")
        else:
            add("work_authorization", "FAIL", f"listing requires {needed_auth}; candidate confirmed {auth}")
    restrictions = el.get("location_restrictions")
    loc = _confirmed(profile, "location")
    if restrictions:
        if loc is None and auth is None:
            add("location", "UNKNOWN", f"listing restricts location to {restrictions}; candidate location not confirmed")
        else:
            pool = _norm_place(" ".join([loc or ""] + list(auth or [])))
            if any(_norm_place(r) & pool for r in restrictions):
                add("location", "PASS", f"candidate location/authorization matches {restrictions}")
            else:
                add("location", "FAIL", f"listing restricts location to {restrictions}")
    s_locs = strict.get("locations") or strict.get("countries")
    if s_locs and d.get("location") and not d.get("remote"):
        if any(_norm_place(x) & _norm_place(d["location"]) for x in s_locs):
            add("campaign_location", "PASS", f"{d['location']} is within the campaign's required locations")
        else:
            add("campaign_location", "FAIL", f"{d['location']} is outside the campaign's required {s_locs}")
    elif s_locs and not d.get("location") and not d.get("remote"):
        add("campaign_location", "UNKNOWN", "listing location is not stated")
    if strict.get("remote") == "ONLY":
        add("remote", "PASS" if d.get("remote") is True else ("FAIL" if d.get("remote") is False else "UNKNOWN"), "campaign requires remote only")
    elif strict.get("remote") == "EXCLUDED" and d.get("remote") is True:
        add("remote", "FAIL", "campaign excludes remote roles")
    if strict.get("paid") is True:
        add("paid", "PASS" if d.get("paid") is True else ("FAIL" if d.get("paid") is False else "UNKNOWN"), "campaign requires paid")
    if el.get("student_required"):
        st = _confirmed(profile, "student_status")
        if st is None:
            add("student_status", "UNKNOWN", "listing requires an enrolled student; status not confirmed")
        else:
            add("student_status", "PASS" if st == "enrolled" else "FAIL", f"candidate status is {st}")
    years = el.get("graduation_years")
    if years:
        gy = _confirmed(profile, "graduation_year")
        if gy is None:
            add("graduation_year", "UNKNOWN", f"listing mentions graduation {years}; candidate year not confirmed")
        else:
            add("graduation_year", "PASS" if gy in years else "FAIL", f"candidate graduates {gy}; listing mentions {years}")
    need_weeks = el.get("min_duration_weeks")
    avail = _confirmed(profile, "availability")
    if need_weeks:
        have = (avail or {}).get("weeks") if isinstance(avail, dict) else None
        if have is None:
            add("duration", "UNKNOWN", f"listing needs about {need_weeks} weeks; availability not confirmed")
        else:
            add("duration", "PASS" if have >= need_weeks else "FAIL", f"available {have} weeks, needs {need_weeks}")
    if strict.get("min_duration_weeks") and need_weeks:
        add("campaign_duration", "PASS" if need_weeks >= strict["min_duration_weeks"] else "FAIL", f"listing about {need_weeks} weeks, campaign minimum {strict['min_duration_weeks']}")
    required = set(el.get("skills_required", [])) | {s.lower() for s in strict.get("must_have_skills", [])}
    if required:
        missing = sorted(required - p_skills)
        add("mandatory_skills", "FAIL" if missing else "PASS", f"missing mandatory skills: {missing}" if missing else "all mandatory skills present on the CV")
    langs = el.get("languages")
    if langs:
        confirmed_langs = _confirmed(profile, "languages")
        known = {k.lower() for k in (confirmed_langs or {})} | {t for l in profile["data"]["languages"] for t in tokens(l["text"])}
        have = [x for x in langs if x.lower() in known or x.lower().split()[0] in known]
        add("language", "PASS" if len(have) == len(langs) else "UNKNOWN", f"listing asks for {langs}; CV/confirmed languages cover {have}")
    return checks


def tier_of(checks: list[dict[str, str]]) -> str:
    if any(c["result"] == "FAIL" for c in checks):
        return "INELIGIBLE"
    if any(c["result"] == "UNKNOWN" for c in checks):
        return "UNKNOWN_ELIGIBILITY"
    return "ELIGIBLE"


def soft_score(profile: dict[str, Any], opp: dict[str, Any], campaign: dict[str, Any] | None) -> dict[str, Any]:
    d, pd = opp["data"], profile["data"]
    el = d.get("eligibility", {})
    p_skills = {s["name"] for s in pd["skills"]}
    opp_skills = set(el.get("skills_required", [])) | set(el.get("skills_preferred", []))
    comp: dict[str, float | None] = {}
    comp["skills"] = (len(p_skills & opp_skills) / len(opp_skills)) if opp_skills else None
    proj_skills = {s for pr in pd["projects"] for s in pr["skills"]}
    comp["projects"] = (len(proj_skills & opp_skills) / len(opp_skills)) if opp_skills and pd["projects"] else (0.0 if opp_skills else None)
    exp_skills = {s for e in pd["experience"] for s in e["skills"]}
    comp["experience"] = (len(exp_skills & opp_skills) / len(opp_skills)) if opp_skills and pd["experience"] else (0.0 if opp_skills else None)
    roles = [r for r in (campaign or {}).get("data", {}).get("roles", [])]
    title_tokens = tokens(d["title"] + " " + (d.get("description") or "")[:400])
    if roles:
        rt = [tokens(r) for r in roles]
        comp["role"] = max((len(t & title_tokens) / len(t)) for t in rt if t) if any(rt) else None
    else:
        comp["role"] = None
    pref = (campaign or {}).get("data", {}).get("remote", "ALLOWED")
    if d.get("remote") is None:
        comp["arrangement"] = 0.5
    elif pref == "ONLY":
        comp["arrangement"] = 1.0 if d["remote"] else 0.0
    elif pref == "EXCLUDED":
        comp["arrangement"] = 0.0 if d["remote"] else 1.0
    else:
        comp["arrangement"] = 1.0
    desc = (d.get("description") or "").lower()
    comp["learning"] = 1.0 if any(t in desc for t in LEARNING_TERMS) else 0.0
    used = {k: v for k, v in comp.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in used)
    score = round(100 * sum(WEIGHTS[k] * v for k, v in used.items()) / total_w) if total_w else None
    return {"score": score, "components": {k: (round(v, 2) if v is not None else None) for k, v in comp.items()}, "coverage": round(total_w / sum(WEIGHTS.values()), 2), "weights": WEIGHTS}


def run_match(ctx: Ctx, p: MatchRun) -> dict[str, Any]:
    rows_out = []
    with ctx.bridge.store.tx() as con:
        profile = latest_profile(con, ctx.workflow_id, p.profile_id)
        campaign = current_campaign(con, ctx.workflow_id)
        opps = entities.listing(con, ctx.workflow_id, "opportunity")
        if p.opportunity_ids:
            wanted = set(p.opportunity_ids)
            opps = [o for o in opps if o["id"] in wanted]
        skipped = {"EXPIRED": 0, "UNKNOWN": 0}
        for o in opps:
            if o["status"] not in MATCHABLE:
                skipped[o["status"]] = skipped.get(o["status"], 0) + 1
                continue
            checks = hard_checks(profile, o, campaign)
            tier = tier_of(checks)
            soft = soft_score(profile, o, campaign)
            rec = {
                "opportunity_id": o["id"], "title": o["data"]["title"], "company_id": o["data"]["company_id"], "listing_status": o["status"],
                "tier": tier, "score": soft["score"], "failed": [c for c in checks if c["result"] == "FAIL"], "unknown": [c for c in checks if c["result"] == "UNKNOWN"],
                "passed": [c["check"] for c in checks if c["result"] == "PASS"], "soft": soft,
            }
            entities.upsert(con, ctx.workflow_id, "match", f"{profile['id']}|{o['id']}", {**rec, "profile_version": profile["data"]["version"]}, status=tier)
            rows_out.append(rec)
    order = {"ELIGIBLE": 0, "UNKNOWN_ELIGIBILITY": 1, "INELIGIBLE": 2}
    ranked = sorted([r for r in rows_out if r["tier"] != "INELIGIBLE"], key=lambda r: (order[r["tier"]], -(r["score"] if r["score"] is not None else -1), r["opportunity_id"]))
    inelig = [r for r in rows_out if r["tier"] == "INELIGIBLE"]
    top = ranked[: p.top]
    tiers = {t: sum(1 for r in rows_out if r["tier"] == t) for t in order}
    return {
        "summary": {
            "matched": len(rows_out), "tiers": tiers, "skipped_not_matchable": skipped,
            "top": [{"opportunity_id": r["opportunity_id"], "title": r["title"], "tier": r["tier"], "score": r["score"], "unknown": [u["check"] for u in r["unknown"]]} for r in top],
        },
        "detail": {
            "ineligible": [{"opportunity_id": r["opportunity_id"], "title": r["title"], "score_hidden_by_failure": r["score"], "failed": r["failed"]} for r in inelig],
            "top_explanations": [{"opportunity_id": r["opportunity_id"], "passed": r["passed"], "unknown": r["unknown"], "soft": r["soft"]} for r in top],
            "weights": WEIGHTS,
        },
        "next": "ask the user to confirm facts behind UNKNOWN checks (career.profile.confirm), then career.application.prepare for chosen opportunities",
    }
