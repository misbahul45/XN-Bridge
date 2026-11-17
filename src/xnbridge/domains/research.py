from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field

from .. import entities
from ..errors import NotFound, ValidationFailed
from ..spec import ActionDef, Ctx, DomainSpec, StageSpec
from ..textutil import canonical_url, normalize_name

SPEC = DomainSpec(
    name="research",
    version=1,
    skill="xn-bridge",
    description="Collect, verify and synthesize research sources",
    stages=(
        StageSpec("collect", "Find candidate sources and register them without duplicates", capabilities=("paper.search",), optional_capabilities=("web.search",), actions=("sources.add",)),
        StageSpec("verify", "Verify each source against captured evidence", capabilities=("web.fetch",), actions=("sources.verify",)),
        StageSpec("synthesize", "Write only claims backed by verified sources", capabilities=(), actions=("brief.finalize",), risk="LOCAL_WRITE"),
    ),
)


class SourceIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    doi: str | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=1900, le=2100)


class AddSources(BaseModel):
    sources: list[SourceIn] = Field(min_length=1, max_length=500)


class VerifySource(BaseModel):
    source_id: str
    evidence_id: str


class ClaimIn(BaseModel):
    text: str = Field(min_length=5, max_length=1000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class FinalizeBrief(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    claims: list[ClaimIn] = Field(min_length=1, max_length=100)


def source_key(s: SourceIn) -> str:
    if s.doi:
        d = s.doi.lower().strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        return f"doi:{d}"
    if s.url:
        return f"url:{canonical_url(s.url)}"
    return f"title:{normalize_name(s.title)}"


def add_sources(ctx: Ctx, p: AddSources) -> dict[str, Any]:
    added = merged = 0
    ids: list[str] = []
    with ctx.bridge.store.tx() as con:
        for s in p.sources:
            ent, created = entities.upsert(
                con, ctx.workflow_id, "source", source_key(s), {"title": s.title, "url": s.url, "doi": s.doi, "year": s.year, "evidence_ids": []}, status="UNVERIFIED",
                merge=lambda old, new: {**old, **{k: v for k, v in new.items() if v and not old.get(k)}},
            )
            added += int(created)
            merged += int(not created)
            ids.append(ent["id"])
    return {"summary": {"added": added, "duplicates_merged": merged, "total_input": len(p.sources)}, "detail": {"source_ids": ids}}


def verify_source(ctx: Ctx, p: VerifySource) -> dict[str, Any]:
    with ctx.bridge.store.tx() as con:
        ent = entities.get(con, p.source_id, ctx.workflow_id, "source")
        ok, reason = source_evidence(ctx, ent, p.evidence_id, con)
        data = ent["data"]
        if not ok:
            return {"summary": {"source_id": p.source_id, "status": ent["status"], "verified": False, "reason": reason}}
        data["evidence_ids"] = sorted(set(data.get("evidence_ids", [])) | {p.evidence_id})
        entities.update(con, ent["id"], data, "VERIFIED")
    return {"summary": {"source_id": p.source_id, "status": "VERIFIED", "verified": True}}


def source_evidence(ctx: Ctx, source: dict, evidence_id: str, con) -> tuple[bool, str]:
    ok, reason = ctx.bridge.evidence.usable_as_verified(evidence_id, con, workflow_id=ctx.workflow_id)
    if not ok:
        return False, reason
    ev = ctx.bridge.evidence.get(evidence_id, con)
    data = source["data"]
    ref = unquote(ev.get("source_ref") or "").lower()
    if data.get("url"):
        return (True, "matching source URL") if canonical_url(ref) == canonical_url(data["url"]) else (False, "evidence URL does not identify this source")
    if data.get("doi"):
        doi = source_key(SourceIn.model_validate(data))[4:]
        arxiv = doi.removeprefix("10.48550/arxiv.")
        parts = urlsplit(ref)
        if ((parts.hostname in ("doi.org", "dx.doi.org") and parts.path.strip("/") == doi)
                or (arxiv != doi and parts.hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org") and parts.path.rstrip("/") == "/abs/" + arxiv)):
            return True, "matching source identifier"
        return False, "evidence does not identify this DOI"
    raw = ctx.bridge.artifacts.read_text(ev["artifact_id"], 32000) if ev.get("artifact_id") else ""
    if " ".join(data["title"].lower().split()) not in " ".join(raw.lower().split()):
        return False, "captured content does not identify this title"
    return True, "matching source title"


def finalize_brief(ctx: Ctx, p: FinalizeBrief) -> dict[str, Any]:
    unsupported: list[dict[str, Any]] = []
    with ctx.bridge.store.tx() as con:
        status = {}
        for source in entities.listing(con, ctx.workflow_id, "source"):
            fresh = source["status"] == "VERIFIED" and any(source_evidence(ctx, source, eid, con)[0] for eid in source["data"].get("evidence_ids", []))
            status[source["id"]] = "VERIFIED" if fresh else "UNVERIFIED"
            if source["status"] == "VERIFIED" and not fresh:
                entities.update(con, source["id"], source["data"], "UNVERIFIED")
        for i, c in enumerate(p.claims):
            backing = [s for s in c.source_ids if status.get(s) == "VERIFIED"]
            if not backing:
                unknown = [s for s in c.source_ids if s not in status]
                unsupported.append({"claim_index": i, "reason": "no VERIFIED source" if not unknown else f"unknown source ids {unknown}"})
        if unsupported:
            return {"summary": {"finalized": False, "unsupported_claims": len(unsupported)}, "detail": {"unsupported": unsupported}}
        ent, _ = entities.upsert(con, ctx.workflow_id, "brief", p.title.lower(), {"title": p.title, "claims": [c.model_dump() for c in p.claims]}, status="FINAL")
    return {"summary": {"finalized": True, "brief_id": ent["id"], "claims": len(p.claims)}}


def actions() -> list[ActionDef]:
    return [
        ActionDef("research", "sources.add", "collect", "LOCAL_WRITE", add_sources, "register sources with deduplication by DOI, URL or title", AddSources),
        ActionDef("research", "sources.verify", "verify", "LOCAL_WRITE", verify_source, "mark a source VERIFIED using fresh captured evidence", VerifySource),
        ActionDef("research", "brief.finalize", "synthesize", "LOCAL_WRITE", finalize_brief, "finalize a brief only if every claim has a verified source", FinalizeBrief),
    ]
