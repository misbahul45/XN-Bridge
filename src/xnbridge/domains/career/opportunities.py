from __future__ import annotations

import re
from html import unescape
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ... import entities
from ...errors import NotFound, PolicyDenied, ValidationFailed
from ...security import scan_untrusted
from ...spec import Ctx
from ...textutil import canonical_url, host_of, registrable_domain
from . import ats as atsmod
from .discovery import current_campaign, get_company, verified_domains
from .model import FetchAts, OpportunitiesIngest, Reverify

CLOSED_RE = re.compile(
    r"no longer (accepting|available|open)|position (has been|is) (filled|closed)|applications? (are |is )?(now )?closed|"
    r"(this )?(job|role|position|posting) (is )?(no longer|has expired)|lowongan (telah |sudah )?(ditutup|berakhir)|pendaftaran (telah |sudah )?ditutup",
    re.I,
)
OFFICIAL_SOURCES = ("ats", "careers_page")
UNOFFICIAL_SOURCES = ("aggregator", "search_result", "user_provided")


def _apply_host_ok(item: dict[str, Any], company: dict[str, Any], via_fetch: bool) -> tuple[bool, str]:
    domains = verified_domains(company)
    hosts = [host_of(item.get("apply_url") or item.get("url") or "")]
    if item["source"] == "careers_page":
        if any(registrable_domain(h) in domains for h in hosts if h):
            return True, "apply route is on a verified company domain"
        return False, "careers page host is not a verified domain of this company"
    if any(registrable_domain(h) in domains for h in hosts if h):
        return True, "apply route is on a verified company domain"
    if via_fetch:
        return True, "fresh official company evidence links to this exact ATS board"
    return False, "no fresh official company evidence links to this ATS board"


def _board_key(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.scheme != "https" or parsed.username or port not in (None, 443) or not parts:
        return None
    providers = {"boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
                 "jobs.lever.co": "lever", "jobs.ashbyhq.com": "ashby"}
    vendor = providers.get(parsed.hostname)
    return (vendor, parts[0]) if vendor else None


def _verified_board_keys(ctx: Ctx, con, company: dict) -> set[tuple[str, str]]:
    """Read fresh employer evidence once per company in this bounded batch."""
    keys = set()
    for domain in company["data"]["domains"]:
        eid = domain.get("evidence_id")
        if not domain["verified"] or not eid:
            continue
        ok, _ = ctx.bridge.evidence.usable_as_verified(eid, con, workflow_id=ctx.workflow_id)
        if not ok:
            continue
        ev = ctx.bridge.evidence.get(eid, con)
        if registrable_domain(host_of(ev["source_ref"] or "")) != domain["domain"] or not ev.get("artifact_id"):
            continue
        try:
            content = unescape(ctx.bridge.artifacts.read_text(ev["artifact_id"]))
        except NotFound:
            continue
        links = re.findall(r'https?://[^\s<>"\)\]\x27]+', content)
        keys.update(key for link in links if (key := _board_key(link.rstrip(".,;"))) is not None)
    return keys


def classify(item: dict[str, Any], company: dict[str, Any], evidence: dict[str, Any] | None, usable: tuple[bool, str] | None, *, via_fetch: bool = False, today: str | None = None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    today = today or datetime.now(UTC).strftime("%Y-%m-%d")
    blob = f"{item.get('title', '')} {item.get('description') or ''}"
    if item.get("deadline") and item["deadline"] < today:
        return "EXPIRED", [f"deadline {item['deadline']} has passed"]
    if CLOSED_RE.search(blob):
        return "EXPIRED", ["listing text says it is closed"]
    if evidence is None:
        return "UNKNOWN", ["no evidence supplied; an opening cannot be assumed from a company's existence"]
    if evidence["verification"] == "UNKNOWN":
        return "UNKNOWN", ["evidence verification is UNKNOWN"]
    ok, why = usable if usable is not None else (False, "evidence not checked")
    if item["source"] == "inquiry":
        if ok:
            return "INQUIRY_ONLY", ["official page offers an inquiry route but no specific opening"]
        return "UNKNOWN", [f"inquiry route not verifiable: {why}"]
    if item.get("flags"):
        return "LISTED_UNCERTAIN", [f"posting text has instruction-like patterns ({','.join(item['flags'])}); needs human review"]
    if not ok:
        return "LISTED_UNCERTAIN", [why]
    if item["source"] in UNOFFICIAL_SOURCES:
        return "LISTED_UNCERTAIN", [f"source '{item['source']}' is not an official page"]
    if company["data"]["identity"] != "VERIFIED":
        return "LISTED_UNCERTAIN", ["company identity is not verified (no verified official domain)"]
    if not item.get("apply_url"):
        return "LISTED_UNCERTAIN", ["no apply route found"]
    ok_host, host_reason = _apply_host_ok(item, company, via_fetch)
    if not ok_host:
        return "LISTED_UNCERTAIN", [host_reason]
    reasons += ["fresh verified evidence from an official source", host_reason]
    return "OPEN_VERIFIED", reasons


def _opp_key(item: dict[str, Any]) -> str:
    if item.get("external_id") and item.get("ats"):
        return f"{item['company_id']}|{item['ats']}:{item['external_id']}"
    return f"{item['company_id']}|{canonical_url(item['url'])}"


def _build(item: dict[str, Any], company_id: str, source: str, evidence_id: str | None, ats: str | None = None) -> dict[str, Any]:
    text = f"{item.get('title', '')}\n{item.get('description') or ''}"
    elig = atsmod.extract_eligibility(text)
    flags = scan_untrusted(text)
    paid = item.get("paid") if item.get("paid") is not None else elig.get("paid")
    remote = item.get("remote") if item.get("remote") is not None else elig.get("remote")
    return {
        "title": item["title"], "company_id": company_id, "url": item["url"], "canonical_url": canonical_url(item["url"]) if item.get("url") else None,
        "apply_url": item.get("apply_url") or item.get("url"), "source": source, "ats": ats, "external_id": item.get("external_id"),
        "location": item.get("location"), "remote": remote, "paid": paid, "deadline": item.get("deadline"),
        "category": item.get("category") or atsmod.guess_category(item["title"], item.get("employment_type")),
        "description": (item.get("description") or "")[:3000], "eligibility": elig, "flags": flags,
        "evidence_ids": [evidence_id] if evidence_id else [], "posted_at": item.get("posted_at"),
        "first_seen": datetime.now(UTC).isoformat(),
    }


def _store(ctx: Ctx, con, company: dict[str, Any], built: dict[str, Any], verified_boards: set) -> tuple[dict[str, Any], bool]:
    ev = None
    usable = None
    if built["evidence_ids"]:
        ev = ctx.bridge.evidence.get(built["evidence_ids"][0], con)
        usable = ctx.bridge.evidence.usable_as_verified(built["evidence_ids"][0], con, workflow_id=ctx.workflow_id)
    key = _board_key(built.get("apply_url") or built.get("url") or "")
    status, reasons = classify(built, company, ev, usable, via_fetch=key is not None and key in verified_boards)
    built["status_reasons"] = reasons

    def merge(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        merged = {**old, **{k: v for k, v in new.items() if v not in (None, "", [], {})}}
        merged["evidence_ids"] = sorted(set(old.get("evidence_ids", [])) | set(new.get("evidence_ids", [])))
        merged["first_seen"] = old.get("first_seen", new.get("first_seen"))
        return merged

    return entities.upsert(con, ctx.workflow_id, "opportunity", _opp_key(built), built, status=status, merge=merge)


def ingest_items(ctx: Ctx, p: OpportunitiesIngest) -> dict[str, Any]:
    added = merged = 0
    counts: dict[str, int] = {}
    with ctx.bridge.store.tx() as con:
        keys_by_company = {}
        for it in p.items:
            company = get_company(con, ctx.workflow_id, it.company_id)
            if it.company_id not in keys_by_company:
                keys_by_company[it.company_id] = _verified_board_keys(ctx, con, company)
            built = _build(it.model_dump(), it.company_id, it.source, it.evidence_id)
            ent, created = _store(ctx, con, company, built, keys_by_company[it.company_id])
            added += int(created)
            merged += int(not created)
            counts[ent["status"]] = counts.get(ent["status"], 0) + 1
    return {"summary": {"added": added, "duplicates_merged": merged, "by_status": counts}}


def fetch_ats(ctx: Ctx, p: FetchAts) -> dict[str, Any]:
    b = ctx.bridge
    with b.store.read() as con:
        company = get_company(con, ctx.workflow_id, p.company_id)
        camp = current_campaign(con, ctx.workflow_id)
    if company["data"]["identity"] != "VERIFIED":
        raise PolicyDenied("company identity must be VERIFIED (career.company.verify_domain) before reading its job board", details={"company_id": p.company_id})
    url, raw = atsmod.fetch_board(p.ats, p.slug, b.settings.policy)
    try:
        jobs = atsmod.PARSERS[p.ats](raw)
    except (ValueError, KeyError, TypeError) as e:
        raise ValidationFailed(f"could not parse {p.ats} response: {type(e).__name__}")
    ev = b.evidence.register(
        workflow_id=ctx.workflow_id, claim=f"{p.ats} board '{p.slug}' lists {len(jobs)} postings", origin="tool_output", requested="VERIFIED",
        source_ref=url, content=raw, provider="xn-bridge:ats", ttl_class="listing", scan_content=False,
    )
    wanted = set(camp["data"]["categories"]) if (camp and p.only_matching_campaign) else None
    expanded = set(wanted or ())
    if "INTERNSHIP_PAID" in expanded or "INTERNSHIP_REMOTE" in expanded:
        expanded.add("INTERNSHIP")
    kept = [j for j in jobs if not wanted or (j["category"] in expanded)]
    added = merged = 0
    counts: dict[str, int] = {}
    with b.store.tx() as con:
        company = get_company(con, ctx.workflow_id, p.company_id)
        verified_boards = _verified_board_keys(ctx, con, company)
        for j in kept:
            built = _build({**j, "company_id": p.company_id}, p.company_id, "ats", ev["id"], ats=p.ats)
            ent, created = _store(ctx, con, company, built, verified_boards)
            added += int(created)
            merged += int(not created)
            counts[ent["status"]] = counts.get(ent["status"], 0) + 1
    return {
        "summary": {"board": f"{p.ats}:{p.slug}", "listed": len(jobs), "kept": len(kept), "added": added, "duplicates_merged": merged, "by_status": counts, "evidence_id": ev["id"], "evidence_verification": ev["verification"]},
        "raw": raw,
    }


def reverify(ctx: Ctx, p: Reverify) -> dict[str, Any]:
    changed = []
    with ctx.bridge.store.tx() as con:
        keys_by_company = {}
        rows = entities.listing(con, ctx.workflow_id, "opportunity")
        if p.opportunity_ids:
            wanted = set(p.opportunity_ids)
            rows = [r for r in rows if r["id"] in wanted]
        for r in rows:
            d = r["data"]
            company = get_company(con, ctx.workflow_id, d["company_id"])
            ev = ctx.bridge.evidence.get(d["evidence_ids"][0], con) if d["evidence_ids"] else None
            usable = ctx.bridge.evidence.usable_as_verified(d["evidence_ids"][0], con, workflow_id=ctx.workflow_id) if d["evidence_ids"] else None
            if d["company_id"] not in keys_by_company:
                keys_by_company[d["company_id"]] = _verified_board_keys(ctx, con, company)
            key = _board_key(d.get("apply_url") or d.get("url") or "")
            status, reasons = classify(d, company, ev, usable, via_fetch=key is not None and key in keys_by_company[d["company_id"]])
            if status != r["status"]:
                changed.append({"opportunity_id": r["id"], "from": r["status"], "to": status, "why": reasons[0]})
                d["status_reasons"] = reasons
                entities.update(con, r["id"], d, status)
    return {"summary": {"checked": len(rows), "changed": len(changed)}, "detail": {"changes": changed}}
