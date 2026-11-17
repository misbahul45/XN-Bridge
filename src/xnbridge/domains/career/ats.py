from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from ...errors import PolicyDenied, Unavailable, ValidationFailed
from ...security import check_url
from ...textutil import html_to_text

MAX_BYTES = 4 * 1024 * 1024
UA = "xn-bridge/0.1 (local, read-only public job boards)"

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
KNOWN_ATS_HOSTS = (
    "boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io", "jobs.lever.co", "api.lever.co", "jobs.ashbyhq.com",
    "api.ashbyhq.com", "apply.workable.com", "smartrecruiters.com", "recruitee.com", "jobs.smartrecruiters.com",
)
CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("RESEARCH_INTERNSHIP", r"research\s+(intern|internship)|magang riset"),
    ("PKL", r"\bpkl\b|praktik kerja|prakerin"),
    ("INTERNSHIP", r"\b(intern|internship|magang|working student|werkstudent|co-?op|trainee)\b"),
    ("GRADUATE", r"\bgraduate\b|\bfresh graduate\b|\bnew grad\b"),
    ("ENTRY_LEVEL", r"\bentry[- ]level\b|\bassociate\b"),
    ("JUNIOR", r"\bjunior\b|\bjr\.?\b"),
    ("PART_TIME", r"\bpart[- ]time\b|\bparuh waktu\b"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, *, timeout: float = 20.0, max_bytes: int = MAX_BYTES) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "json" not in ctype.lower():
                raise ValidationFailed(f"unexpected content type '{ctype}' from ATS endpoint")
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        raise Unavailable(f"ATS endpoint returned HTTP {e.code}", details={"http_status": e.code})
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unavailable(f"ATS endpoint unreachable: {type(e).__name__}")
    if len(data) > max_bytes:
        raise ValidationFailed("ATS response exceeds the size limit")
    return data


def board_url(ats: str, slug: str) -> str:
    if ats not in ENDPOINTS:
        raise ValidationFailed(f"unsupported ATS '{ats}'")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}", slug):
        raise ValidationFailed("invalid board slug")
    return ENDPOINTS[ats].format(slug=slug)


def fetch_board(ats: str, slug: str, settings_policy: dict[str, Any]) -> tuple[str, bytes]:
    if settings_policy["network"]["offline"]:
        raise Unavailable("offline mode: bridge-side ATS fetch is disabled")
    url = board_url(ats, slug)
    host = url.split("/")[2]
    if host not in settings_policy["network"]["allowed_ats_hosts"]:
        raise PolicyDenied(f"host {host} is not in the ATS allowlist")
    check = check_url(url)
    if not check.ok:
        raise PolicyDenied(f"url rejected: {check.reason}")
    return url, http_get(url)


def guess_category(*texts: str | None) -> str | None:
    blob = " ".join(t for t in texts if t)
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, blob, re.I):
            return cat
    return None


def _norm(title: str, ext: str, url: str, apply_url: str | None, location: str | None, remote: bool | None, employment: str | None, posted: str | None, desc: str | None) -> dict[str, Any]:
    return {
        "title": title.strip()[:300], "external_id": str(ext), "url": url, "apply_url": apply_url or url, "location": (location or "").strip()[:200] or None,
        "remote": remote, "employment_type": employment, "posted_at": posted, "description": (desc or "")[:6000],
        "category": guess_category(title, employment),
    }


def parse_greenhouse(raw: bytes) -> list[dict[str, Any]]:
    out = []
    for j in json.loads(raw).get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        desc = html_to_text(j.get("content") or "", 6000)
        out.append(_norm(j.get("title", ""), j.get("id", ""), j.get("absolute_url", ""), j.get("absolute_url"), loc, True if loc and re.search(r"remote", loc, re.I) else None, None, j.get("updated_at"), desc))
    return out


def parse_lever(raw: bytes) -> list[dict[str, Any]]:
    out = []
    data = json.loads(raw)
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        wt = (j.get("workplaceType") or "").lower()
        remote = True if wt == "remote" else (False if wt == "on-site" else None)
        out.append(_norm(j.get("text", ""), j.get("id", ""), j.get("hostedUrl", ""), j.get("applyUrl"), cats.get("location"), remote, cats.get("commitment"), str(j.get("createdAt") or ""), j.get("descriptionPlain")))
    return out


def parse_ashby(raw: bytes) -> list[dict[str, Any]]:
    out = []
    for j in json.loads(raw).get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append(_norm(j.get("title", ""), j.get("id", ""), j.get("jobUrl", ""), j.get("applyUrl"), j.get("location"), j.get("isRemote"), j.get("employmentType"), j.get("publishedAt"), j.get("descriptionPlain")))
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}

_STUDENT = re.compile(r"(currently|actively)\s+(enrolled|pursuing|studying)|current(ly)? (a )?student|pursuing (a|an) (bachelor|master|degree|undergraduate)|mahasiswa aktif|enrolled in (a|an) (university|degree|bachelor|master)", re.I)
_GRAD = re.compile(r"graduat\w*[^\n.]{0,40}?((?:20)\d{2})", re.I)
_AUTH = re.compile(r"(?:authori[sz]ed|eligible|legally entitled|right)\s+to\s+work\s+(?:in|within)\s+(?:the\s+)?([A-Z][A-Za-z.\- ]{2,40}?)(?=[,.;\n]| without| and |$)")
_CITIZEN = re.compile(r"(?:must be|need to be)\s+(?:an?\s+)?(?:citizen|resident|national)s?\s+(?:of|in)\s+(?:the\s+)?([A-Z][A-Za-z.\- ]{2,40}?)(?=[,.;\n]| and |$)")
_NOSPONSOR = re.compile(r"(?:no|not|cannot|unable to)\s+(?:\w+\s+){0,3}(?:visa\s+)?sponsorship|sponsorship\s+(?:is\s+)?not\s+(?:available|provided|offered)|do(?:es)? not (?:offer|provide) (?:visa )?sponsorship", re.I)
_BASED = re.compile(r"must\s+(?:be\s+)?(?:located|based|reside|living)\s+(?:in|within)\s+(?:the\s+)?([A-Z][A-Za-z.\- ,]{2,50}?)(?=[.;\n]| and |$)")
_DURATION = re.compile(r"(\d{1,2})(?:\s*(?:-|to|–)\s*(\d{1,2}))?\s*(months?|weeks?|bulan|minggu)", re.I)
_LANG = re.compile(r"(?:fluent|proficient|proficiency|fluency|native)\s+(?:in\s+)?(English|Indonesian|Bahasa Indonesia|Mandarin|Chinese|Japanese|German|French|Spanish|Korean|Dutch|Arabic)|(English|Indonesian|Bahasa Indonesia|Mandarin|Japanese|German|French|Spanish|Korean|Dutch|Arabic)\s+(?:proficiency|fluency|language skills)", re.I)
_UNPAID = re.compile(r"\bunpaid\b|\bvolunteer\b|tanpa (gaji|bayaran)", re.I)
_PAID = re.compile(r"\b(paid|stipend|compensation|salary|allowance|uang saku|gaji|honorarium)\b", re.I)
_REMOTE_YES = re.compile(r"fully remote|100% remote|remote[- ]first|work from anywhere|remote position|remote internship", re.I)
_REMOTE_NO = re.compile(r"\bon[- ]?site\b|in[- ]office|in[- ]person|wfo\b", re.I)
_REQ_HEAD = re.compile(r"^\W*(requirements?|qualifications?|must[- ]have|what you(?:'|’)ll need|what we(?:'|’)re looking for|you have|persyaratan|kualifikasi|minimum qualifications?)\W*:?\s*$", re.I)
_PREF_HEAD = re.compile(r"^\W*(nice[- ]to[- ]have|preferred|bonus|good to have|plus|pluses|diutamakan)\W*:?\s*$", re.I)
_MANDATORY_WORD = re.compile(r"\b(required|must|wajib|minimum|proficien\w+|strong|solid|experience (with|in))\b", re.I)


def extract_eligibility(text: str) -> dict[str, Any]:
    from .profile import find_skills

    elig: dict[str, Any] = {}
    src: dict[str, str] = {}

    def keep(key: str, m: re.Match) -> None:
        s = max(0, m.start() - 20)
        src[key] = " ".join(text[s : m.end() + 40].split())[:140]

    m = _STUDENT.search(text)
    if m:
        elig["student_required"] = True
        keep("student_required", m)
    years = sorted({int(y) for y in _GRAD.findall(text)})
    if years:
        elig["graduation_years"] = years
        keep("graduation_years", _GRAD.search(text))
    auth = [a.strip() for a in _AUTH.findall(text)] + [a.strip() for a in _CITIZEN.findall(text)]
    if auth:
        elig["work_authorization"] = sorted(set(auth))
        keep("work_authorization", _AUTH.search(text) or _CITIZEN.search(text))
    if _NOSPONSOR.search(text):
        elig["sponsorship"] = False
        keep("sponsorship", _NOSPONSOR.search(text))
    based = [b.strip() for b in _BASED.findall(text)]
    if based:
        elig["location_restrictions"] = sorted(set(based))
        keep("location_restrictions", _BASED.search(text))
    durations = []
    for m in _DURATION.finditer(text):
        lo = int(m.group(1))
        unit = m.group(3).lower()
        durations.append(round(lo * (4.33 if unit.startswith(("month", "bulan")) else 1)))
    if durations:
        elig["min_duration_weeks"] = min(durations)
    langs = sorted({(a or b).title() for a, b in _LANG.findall(text)})
    if langs:
        elig["languages"] = langs
    if _UNPAID.search(text):
        elig["paid"] = False
    elif _PAID.search(text):
        elig["paid"] = True
    if _REMOTE_YES.search(text):
        elig["remote"] = True
    elif _REMOTE_NO.search(text):
        elig["remote"] = False
    required: set[str] = set()
    preferred: set[str] = set()
    mode = None
    for line in text.splitlines():
        if _REQ_HEAD.match(line):
            mode = "req"
            continue
        if _PREF_HEAD.match(line):
            mode = "pref"
            continue
        if mode and not line.strip():
            continue
        sk = set(find_skills(line))
        if not sk:
            continue
        if mode == "pref":
            preferred |= sk
        elif mode == "req" and _MANDATORY_WORD.search(line):
            required |= sk
        elif mode == "req":
            preferred |= sk
        else:
            preferred |= sk
    elig["skills_required"] = sorted(required)
    elig["skills_preferred"] = sorted(preferred - required)
    elig["sources"] = src
    return elig
