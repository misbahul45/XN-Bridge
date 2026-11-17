from __future__ import annotations

import itertools
from typing import Any

from ... import entities
from ...errors import NotFound, ValidationFailed
from ...security import check_url, digest_obj
from ...spec import Ctx
from ...textutil import host_of, is_aggregator, normalize_name, registrable_domain
from .model import CampaignDefine, CompaniesAdd, VerifyDomain

CATEGORY_TERMS = {
    "PKL": ["PKL", "internship"],
    "INTERNSHIP": ["internship"],
    "INTERNSHIP_PAID": ["paid internship"],
    "INTERNSHIP_REMOTE": ["remote internship"],
    "RESEARCH_INTERNSHIP": ["research internship"],
    "GRADUATE": ["graduate program"],
    "ENTRY_LEVEL": ["entry level"],
    "JUNIOR": ["junior"],
    "PART_TIME": ["part-time"],
}
LOCAL_TERMS = {
    "indonesia": {"PKL": ["praktik kerja lapangan", "magang PKL"], "INTERNSHIP": ["magang"], "INTERNSHIP_PAID": ["magang berbayar"], "ENTRY_LEVEL": ["lowongan fresh graduate"]},
}
INDONESIAN_PLACES = {"indonesia", "id", "jakarta", "surabaya", "bandung", "yogyakarta", "malang", "semarang", "medan", "depok", "tangerang", "bekasi", "bogor", "denpasar", "makassar", "sidoarjo", "gresik", "bali"}


def _clean(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        s = " ".join(it.split())
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def build_queries(p: CampaignDefine, cats: list[str], locations: list[str], countries: list[str]) -> list[str]:
    places = locations or countries
    local = any(x.lower() in INDONESIAN_PLACES for x in places)
    roles = p.roles or [""]
    if p.scope in ("WORLDWIDE", "REMOTE_WORLDWIDE") and not places:
        places = ["remote" if p.scope == "REMOTE_WORLDWIDE" else "worldwide"]
    term_lists: list[list[str]] = []
    for c in cats:
        terms = list(CATEGORY_TERMS.get(c, [c.lower()]))
        if local:
            terms += LOCAL_TERMS["indonesia"].get(c, [])
        term_lists.append(terms)
    max_len = max((len(t) for t in term_lists), default=1)
    combos: list[tuple[str, str, str]] = []
    for ti in range(max_len):
        for role, place, terms in itertools.product(roles, places or [""], term_lists):
            if ti < len(terms):
                combos.append((role, terms[ti], place))
    seen, queries = set(), []
    for role, term, place in combos:
        q = " ".join(x for x in (role, term, place) if x).strip()
        if q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)
        if len(queries) >= p.max_searches:
            break
    return queries


def define_campaign(ctx: Ctx, p: CampaignDefine) -> dict[str, Any]:
    cats = list(dict.fromkeys(p.categories))
    if "INTERNSHIP_REMOTE" in cats and p.remote == "EXCLUDED":
        raise ValidationFailed("INTERNSHIP_REMOTE conflicts with remote=EXCLUDED")
    if p.scope == "REMOTE_WORLDWIDE" and p.remote == "EXCLUDED":
        raise ValidationFailed("REMOTE_WORLDWIDE conflicts with remote=EXCLUDED")
    paid = p.paid
    if "INTERNSHIP_PAID" in cats:
        if p.strict.paid is False or paid is False:
            raise ValidationFailed("INTERNSHIP_PAID conflicts with paid=false")
        paid = True
    if p.strict.paid is True and paid is False:
        raise ValidationFailed("strict.paid=true conflicts with paid=false")
    strict = p.strict.model_dump()
    strict["categories"] = list(dict.fromkeys(strict["categories"]))
    if strict["min_duration_weeks"] and strict["max_duration_weeks"] and strict["min_duration_weeks"] > strict["max_duration_weeks"]:
        raise ValidationFailed("strict.min_duration_weeks exceeds max_duration_weeks")
    locations, countries = _clean(p.locations), _clean(p.countries)
    data = {
        "roles": _clean(p.roles),
        "categories": cats,
        "locations": locations,
        "countries": countries,
        "scope": p.scope,
        "remote": p.remote,
        "paid": paid,
        "industries": _clean(p.industries),
        "skills": _clean(p.skills),
        "strict": strict,
        "preferences": p.preferences,
        "limits": {"max_searches": p.max_searches, "max_companies": p.max_companies},
    }
    data["queries"] = build_queries(p, cats, locations, countries)
    digest = digest_obj({k: v for k, v in data.items() if k != "queries"})
    with ctx.bridge.store.tx() as con:
        ent, created = entities.upsert(con, ctx.workflow_id, "campaign", digest[:16], data, status="ACTIVE")
        entities.upsert(con, ctx.workflow_id, "campaign_head", "head", {"campaign_id": ent["id"]})
    hard = [k for k, v in strict.items() if v not in (None, [], False)]
    return {
        "summary": {
            "campaign_id": ent["id"], "created": created, "categories": cats, "scope": p.scope, "remote": p.remote, "paid": paid,
            "locations": locations or countries, "hard_constraints": hard, "query_count": len(data["queries"]),
        },
        "detail": {"queries": data["queries"], "strict": strict, "preferences": p.preferences},
        "next": "run the queries with web.search (capability_resolve), then career.companies.add with the companies found",
    }


def current_campaign(con, workflow_id: str) -> dict[str, Any] | None:
    head = entities.find(con, workflow_id, "campaign_head", "head")
    if head is None:
        return None
    return entities.get(con, head["data"]["campaign_id"], workflow_id, "campaign")


def _company_indexes(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_domain: dict[str, dict[str, Any]] = {}
    by_norm: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_norm[r["data"]["norm"]] = r
        for d in r["data"]["domains"]:
            by_domain[d["domain"]] = r
    return by_domain, by_norm


def add_companies(ctx: Ctx, p: CompaniesAdd) -> dict[str, Any]:
    added, merged, rejected = [], [], []
    with ctx.bridge.store.tx() as con:
        rows = entities.listing(con, ctx.workflow_id, "company")
        by_domain, by_norm = _company_indexes(rows)
        limit = None
        camp = current_campaign(con, ctx.workflow_id)
        if camp:
            limit = camp["data"]["limits"]["max_companies"]
        for c in p.companies:
            norm = normalize_name(c.name)
            if not norm:
                rejected.append({"name": c.name, "reason": "name has no usable characters"})
                continue
            domain = None
            note = None
            if c.url:
                chk = check_url(c.url, resolve=False)
                if not chk.ok:
                    rejected.append({"name": c.name, "reason": f"url rejected: {chk.reason}"})
                    continue
                d = registrable_domain(host_of(c.url))
                if is_aggregator(d):
                    note = "aggregator or social domain ignored for identity"
                else:
                    domain = d
            source = {"source": c.source, "source_ref": c.source_ref, "url": c.url}
            existing = by_domain.get(domain) if domain else None
            via = "domain"
            if existing is None:
                existing = by_norm.get(norm)
                via = "name"
            if existing is not None:
                data = existing["data"]
                if c.name not in data["aliases"] and c.name != data["name"]:
                    data["aliases"].append(c.name)
                data["sources"].append(source)
                if domain and domain not in {d["domain"] for d in data["domains"]}:
                    data["domains"].append({"domain": domain, "verified": False, "evidence_id": None})
                    by_domain[domain] = existing
                for k, v in (("country", c.country), ("industry", c.industry)):
                    if v and not data.get(k):
                        data[k] = v
                entities.update(con, existing["id"], data)
                merged.append({"company_id": existing["id"], "name": c.name, "matched_by": via})
                continue
            if limit is not None and len(rows) + len(added) >= limit:
                rejected.append({"name": c.name, "reason": f"campaign max_companies={limit} reached"})
                continue
            data = {
                "name": c.name, "aliases": [], "norm": norm,
                "domains": [{"domain": domain, "verified": False, "evidence_id": None}] if domain else [],
                "country": c.country, "industry": c.industry, "sources": [source],
                "identity": "INFERRED" if domain else "UNKNOWN", "note": note,
            }
            ent, _ = entities.upsert(con, ctx.workflow_id, "company", f"n:{norm}", data, status=data["identity"])
            row = {"id": ent["id"], "data": data}
            by_norm[norm] = row
            if domain:
                by_domain[domain] = row
            added.append({"company_id": ent["id"], "name": c.name})
    return {
        "summary": {"added": len(added), "merged_duplicates": len(merged), "rejected": len(rejected), "input": len(p.companies)},
        "detail": {"added_list": added, "merged_list": merged, "rejected_list": rejected},
        "next": "verify each company's official domain with career.company.verify_domain using fetched evidence of the official site",
    }


def verify_domain(ctx: Ctx, p: VerifyDomain) -> dict[str, Any]:
    domain = registrable_domain(p.domain.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0])
    if is_aggregator(domain):
        return {"summary": {"company_id": p.company_id, "verified": False, "reason": "aggregator or social domain cannot identify a company"}}
    ok, why = ctx.bridge.evidence.usable_as_verified(p.evidence_id, workflow_id=ctx.workflow_id)
    if not ok:
        return {"summary": {"company_id": p.company_id, "verified": False, "reason": why}}
    ev = ctx.bridge.evidence.get(p.evidence_id)
    ev_domain = registrable_domain(host_of(ev["source_ref"] or ""))
    if ev_domain != domain:
        return {"summary": {"company_id": p.company_id, "verified": False, "reason": f"evidence source is {ev_domain or 'not a web page'}, not {domain}"}}
    with ctx.bridge.store.tx() as con:
        comp = entities.get(con, p.company_id, ctx.workflow_id, "company")
        for other in entities.listing(con, ctx.workflow_id, "company"):
            if other["id"] != comp["id"] and any(d["domain"] == domain and d["verified"] for d in other["data"]["domains"]):
                return {"summary": {"company_id": p.company_id, "verified": False, "reason": "domain already verified for another company", "duplicate_of": other["id"]}}
        data = comp["data"]
        for d in data["domains"]:
            if d["domain"] == domain:
                d["verified"], d["evidence_id"] = True, p.evidence_id
                break
        else:
            data["domains"].append({"domain": domain, "verified": True, "evidence_id": p.evidence_id})
        data["identity"] = "VERIFIED"
        entities.update(con, comp["id"], data, "VERIFIED")
    return {"summary": {"company_id": p.company_id, "verified": True, "domain": domain, "identity": "VERIFIED"}}


def verified_domains(company: dict[str, Any]) -> set[str]:
    return {d["domain"] for d in company["data"]["domains"] if d["verified"]}


def get_company(con, workflow_id: str, company_id: str) -> dict[str, Any]:
    try:
        return entities.get(con, company_id, workflow_id, "company")
    except NotFound:
        raise NotFound(f"company '{company_id}' not found in this workflow")
