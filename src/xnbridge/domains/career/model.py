from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CATEGORIES = ("PKL", "INTERNSHIP", "INTERNSHIP_PAID", "INTERNSHIP_REMOTE", "RESEARCH_INTERNSHIP", "GRADUATE", "ENTRY_LEVEL", "JUNIOR", "PART_TIME")
Category = Literal["PKL", "INTERNSHIP", "INTERNSHIP_PAID", "INTERNSHIP_REMOTE", "RESEARCH_INTERNSHIP", "GRADUATE", "ENTRY_LEVEL", "JUNIOR", "PART_TIME"]
OpportunityStatus = Literal["OPEN_VERIFIED", "LISTED_UNCERTAIN", "EXPIRED", "INQUIRY_ONLY", "UNKNOWN"]
Source = Literal["ats", "careers_page", "search_result", "aggregator", "user_provided", "inquiry"]
AtsName = Literal["greenhouse", "lever", "ashby"]
Channel = Literal["BROWSER_FORM", "EMAIL", "ATS_API"]
AppStatus = Literal[
    "PREPARED", "AWAITING_APPROVAL", "SUBMITTED", "ACKNOWLEDGED", "UNDER_REVIEW", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "OUTCOME_UNKNOWN",
]

FACT_TYPES: dict[str, Any] = {
    "full_name": str,
    "location": str,
    "work_preference": ("remote", "onsite", "hybrid", "any"),
    "student_status": ("enrolled", "graduated", "gap"),
    "graduation_year": int,
    "gpa": float,
    "willing_to_relocate": bool,
    "work_authorization": list,
    "languages": dict,
    "availability": dict,
    "contact": dict,
    "links": dict,
}
SENSITIVE_FACTS = {"contact", "full_name"}


class ProfileIngest(BaseModel):
    text: str | None = Field(default=None, max_length=200_000)
    path: str | None = Field(default=None, max_length=1000)
    extractor: str = Field(default="manual", max_length=60)
    label: str | None = Field(default=None, max_length=120)
    evidence_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def one_source(self):
        if (self.text is None) == (self.path is None):
            raise ValueError("provide exactly one of text or path")
        return self


class ProfileConfirm(BaseModel):
    facts: dict[str, Any] = Field(min_length=1, max_length=12)
    quote: str = Field(min_length=3, max_length=500)

    @field_validator("facts")
    @classmethod
    def valid_facts(cls, v: dict[str, Any]) -> dict[str, Any]:
        for k, val in v.items():
            if k not in FACT_TYPES:
                raise ValueError(f"unknown fact '{k}'; allowed: {sorted(FACT_TYPES)}")
            t = FACT_TYPES[k]
            if isinstance(t, tuple):
                if val not in t:
                    raise ValueError(f"{k} must be one of {t}")
            elif t is float:
                if isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 <= float(val) <= 4.0:
                    raise ValueError("gpa must be a number between 0 and 4.0")
            elif t is int:
                if isinstance(val, bool) or not isinstance(val, int) or not 1990 <= val <= 2100:
                    raise ValueError("graduation_year must be an integer year")
            elif t is bool:
                if not isinstance(val, bool):
                    raise ValueError(f"{k} must be true or false")
            elif not isinstance(val, t):
                raise ValueError(f"{k} must be {t.__name__}")
        return v


class Strict(BaseModel):
    locations: list[str] = Field(default_factory=list, max_length=20)
    countries: list[str] = Field(default_factory=list, max_length=20)
    remote: Literal["ONLY", "ALLOWED", "EXCLUDED"] | None = None
    paid: bool | None = None
    categories: list[Category] = Field(default_factory=list)
    min_duration_weeks: int | None = Field(default=None, ge=1, le=104)
    max_duration_weeks: int | None = Field(default=None, ge=1, le=104)
    must_have_skills: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=10)


class CampaignDefine(BaseModel):
    roles: list[str] = Field(default_factory=list, max_length=10)
    categories: list[Category] = Field(min_length=1, max_length=9)
    locations: list[str] = Field(default_factory=list, max_length=20)
    countries: list[str] = Field(default_factory=list, max_length=20)
    scope: Literal["LOCAL", "REGIONAL", "NATIONAL", "MULTI_COUNTRY", "WORLDWIDE", "REMOTE_WORLDWIDE"] = "LOCAL"
    remote: Literal["ONLY", "ALLOWED", "EXCLUDED"] = "ALLOWED"
    paid: bool | None = None
    industries: list[str] = Field(default_factory=list, max_length=10)
    skills: list[str] = Field(default_factory=list, max_length=30)
    strict: Strict = Field(default_factory=Strict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    max_searches: int = Field(default=12, ge=1, le=60)
    max_companies: int = Field(default=60, ge=1, le=500)

    @model_validator(mode="after")
    def location_or_remote(self):
        if self.scope in ("LOCAL", "REGIONAL", "NATIONAL", "MULTI_COUNTRY") and not (self.locations or self.countries):
            raise ValueError("scope needs locations or countries (or use WORLDWIDE / REMOTE_WORLDWIDE)")
        return self


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    source: Literal["search", "directory", "user_provided", "official", "listing"] = "search"
    source_ref: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=80)
    industry: str | None = Field(default=None, max_length=120)


class CompaniesAdd(BaseModel):
    companies: list[CompanyIn] = Field(min_length=1, max_length=500)


class VerifyDomain(BaseModel):
    company_id: str
    domain: str = Field(min_length=3, max_length=255)
    evidence_id: str


class FetchAts(BaseModel):
    company_id: str
    ats: AtsName
    slug: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
    only_matching_campaign: bool = True


class OpportunityIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    company_id: str
    url: str = Field(max_length=2000)
    apply_url: str | None = Field(default=None, max_length=2000)
    source: Source
    evidence_id: str | None = None
    location: str | None = Field(default=None, max_length=200)
    remote: bool | None = None
    paid: bool | None = None
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str | None = Field(default=None, max_length=20_000)
    external_id: str | None = Field(default=None, max_length=120)
    category: Category | None = None


class OpportunitiesIngest(BaseModel):
    items: list[OpportunityIn] = Field(min_length=1, max_length=500)


class Reverify(BaseModel):
    opportunity_ids: list[str] = Field(default_factory=list, max_length=500)


class MatchRun(BaseModel):
    opportunity_ids: list[str] = Field(default_factory=list, max_length=500)
    profile_id: str | None = None
    top: int = Field(default=10, ge=1, le=50)


class ApplicationPrepare(BaseModel):
    opportunity_id: str
    channel: Channel = "BROWSER_FORM"
    acknowledge_unknown_eligibility: bool = False


class DraftCheck(BaseModel):
    application_id: str
    texts: dict[str, str] = Field(min_length=1, max_length=6)

    @field_validator("texts")
    @classmethod
    def sized(cls, v: dict[str, str]) -> dict[str, str]:
        for k, t in v.items():
            if len(t) > 20_000:
                raise ValueError(f"text '{k}' exceeds 20000 characters")
        return v


class FormField(BaseModel):
    ref: str | None = Field(default=None, max_length=40)
    role: str = Field(max_length=30)
    label: str = Field(max_length=300)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=60)
    step: int = Field(default=1, ge=1, le=20)
    depends_on: dict[str, str] | None = None


class FormParse(BaseModel):
    text: str | None = Field(default=None, max_length=200_000)
    artifact_id: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.text is None) == (self.artifact_id is None):
            raise ValueError("provide exactly one of text or artifact_id")
        return self


class FormPlan(BaseModel):
    application_id: str
    fields: list[FormField] = Field(min_length=1, max_length=300)


class Declaration(BaseModel):
    label: str = Field(max_length=300)
    answer: str = Field(max_length=300)
    user_confirmed: bool = False
    quote: str | None = Field(default=None, max_length=500)


class Attachment(BaseModel):
    name: str = Field(max_length=200)
    artifact_id: str


class SubmissionPrepare(BaseModel):
    application_id: str
    target_url: str = Field(max_length=2000)
    texts: dict[str, str] = Field(default_factory=dict, max_length=6)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)
    declarations: list[Declaration] = Field(default_factory=list, max_length=40)
    form_plan_digest: str | None = Field(default=None, max_length=80)


class TrackingUpdate(BaseModel):
    application_id: str
    status: AppStatus
    evidence_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class Report(BaseModel):
    pass


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
