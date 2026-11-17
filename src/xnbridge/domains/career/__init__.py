from __future__ import annotations

from ...spec import ActionDef, DomainSpec, StageSpec
from . import applications, discovery, matching, opportunities, profile
from .model import (
    ApplicationPrepare, CampaignDefine, CompaniesAdd, DraftCheck, FetchAts, FormParse, FormPlan, MatchRun, OpportunitiesIngest,
    ProfileConfirm, ProfileIngest, Report, Reverify, SubmissionPrepare, TrackingUpdate, VerifyDomain,
)

SPEC = DomainSpec(
    name="career",
    version=1,
    skill="xn-career",
    description="PKL, internships and entry-level applications: discover, verify, match, prepare, supervise submission, track",
    stages=(
        StageSpec("candidate-profile", "Turn the CV into a versioned profile; keep unknown facts unknown and ask the user to confirm them", optional_capabilities=("document.extract",), references=("references/profile.md",), risk="LOCAL_WRITE", actions=("profile.ingest", "profile.confirm")),
        StageSpec("campaign", "Normalize the request into hard constraints and soft preferences with search queries", references=("references/campaign.md",), risk="LOCAL_WRITE", actions=("campaign.define",)),
        StageSpec("company-discovery", "Find and deduplicate candidate companies", capabilities=("web.search",), optional_capabilities=("career.listings",), references=("references/discovery.md",), actions=("companies.add",)),
        StageSpec("company-verification", "Verify each company's official domain from fetched evidence", capabilities=("web.fetch",), optional_capabilities=("browser.inspect",), references=("references/verification.md",), actions=("company.verify_domain",)),
        StageSpec("opportunity-verification", "Collect listings and classify each one from evidence", capabilities=("ats.board_read",), optional_capabilities=("career.listings", "web.fetch", "browser.inspect"), references=("references/opportunities.md",), actions=("opportunities.fetch_ats", "opportunities.ingest", "opportunity.reverify")),
        StageSpec("matching", "Eligibility-first matching: hard checks before any soft score", references=("references/matching.md",), actions=("match.run",)),
        StageSpec("application-preparation", "Prepare drafts from verified facts, check them, plan the form", optional_capabilities=("document.generate", "browser.inspect"), references=("references/application.md",), risk="LOCAL_WRITE", actions=("application.prepare", "draft.check", "form.parse_snapshot", "form.plan")),
        StageSpec("submission", "Supervised external submission with a human-granted, payload-bound approval", capabilities=("browser.form_fill",), optional_capabilities=("browser.upload",), references=("references/submission.md",), risk="EXTERNAL_WRITE", actions=("submission.prepare",)),
        StageSpec("tracking", "Track status changes with evidence", references=("references/tracking.md",), risk="LOCAL_WRITE", optional=True, actions=("tracking.update", "report.pipeline")),
    ),
)


def actions() -> list[ActionDef]:
    d = "career"
    return [
        ActionDef(d, "profile.ingest", "candidate-profile", "LOCAL_WRITE", profile.ingest, "extract a versioned profile from CV text or a local .md/.txt file", ProfileIngest),
        ActionDef(d, "profile.confirm", "candidate-profile", "LOCAL_WRITE", profile.confirm, "record user-confirmed facts (availability, authorization, status) with a quote", ProfileConfirm),
        ActionDef(d, "campaign.define", "campaign", "LOCAL_WRITE", discovery.define_campaign, "normalize a search campaign and generate bounded queries", CampaignDefine),
        ActionDef(d, "companies.add", "company-discovery", "LOCAL_WRITE", discovery.add_companies, "add companies with deduplication by verified domain or exact normalized name", CompaniesAdd),
        ActionDef(d, "company.verify_domain", "company-verification", "LOCAL_WRITE", discovery.verify_domain, "verify an official domain using fresh VERIFIED evidence from that domain", VerifyDomain),
        ActionDef(d, "opportunities.fetch_ats", "opportunity-verification", "LOCAL_WRITE", opportunities.fetch_ats, "read a public ATS board and persist verified listings", FetchAts),
        ActionDef(d, "opportunities.ingest", "opportunity-verification", "LOCAL_WRITE", opportunities.ingest_items, "classify listings found elsewhere from their evidence", OpportunitiesIngest),
        ActionDef(d, "opportunity.reverify", "opportunity-verification", "LOCAL_WRITE", opportunities.reverify, "recompute listing status; stale evidence demotes OPEN_VERIFIED", Reverify),
        ActionDef(d, "match.run", "matching", "LOCAL_WRITE", matching.run_match, "eligibility-first matching with transparent soft scores", MatchRun),
        ActionDef(d, "application.prepare", "application-preparation", "LOCAL_WRITE", applications.prepare, "create an application with a fact pack and truthful draft skeletons", ApplicationPrepare),
        ActionDef(d, "draft.check", "application-preparation", "LOCAL_WRITE", applications.check_draft, "flag claims in drafts that the CV or listing does not support", DraftCheck),
        ActionDef(d, "form.parse_snapshot", "application-preparation", "READ", applications.parse_form, "parse a browser accessibility snapshot into form fields", FormParse),
        ActionDef(d, "form.plan", "application-preparation", "LOCAL_WRITE", applications.plan_form, "plan each field: fill, draft, upload, ask the user, or block", FormPlan),
        ActionDef(d, "submission.prepare", "submission", "LOCAL_WRITE", applications.prepare_submission, "build the submission manifest that a human will approve", SubmissionPrepare),
        ActionDef(d, "tracking.update", "tracking", "LOCAL_WRITE", applications.update_tracking, "move an application status; later statuses need evidence", TrackingUpdate, safe_when_pending=True),
        ActionDef(d, "report.pipeline", "tracking", "READ", applications.pipeline_report, "funnel counts by status", Report),
    ]
