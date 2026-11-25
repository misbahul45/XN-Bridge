from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import entities
from ..errors import ValidationFailed
from ..spec import ActionDef, Ctx, DomainSpec, StageSpec

SERVER = "xn-interact"

SPEC = DomainSpec(
    name="social",
    version=1,
    skill="xn-social",
    description="Connect, inspect, prepare, act on and verify social accounts through XN-Interact",
    stages=(
        StageSpec("connect", "Connect or reauthorize the accounts the task needs", optional_capabilities=("social.account.connect", "social.account.status"), risk="LOCAL_WRITE", optional=True),
        StageSpec("inspect", "Resolve explicit target accounts and their capability verdicts", capabilities=("social.account.list", "social.capability.read"), optional_capabilities=("social.health",), actions=("targets.set",)),
        StageSpec("collect", "Read content, engagement, search results or analytics", optional_capabilities=("social.content.read", "social.engagement.read", "social.search", "social.analytics.read", "social.linkedin.read"), optional=True),
        StageSpec("prepare", "Prepare a local draft, media and per-provider previews", optional_capabilities=("social.content.draft", "social.media.stage"), risk="LOCAL_WRITE", optional=True),
        StageSpec(
            "act",
            "Plan, obtain both approvals, execute once and record the attempt",
            optional_capabilities=("social.content.publish", "social.content.update", "social.content.delete", "social.engagement.act", "social.workflow.run", "social.workflow.cancel", "social.account.disconnect", "social.approval.status"),
            risk="EXTERNAL_WRITE",
            optional=True,
            actions=("plan.record",),
        ),
        StageSpec("verify", "Record per-target outcomes and evidence", capabilities=("social.workflow.status",), optional_capabilities=("social.content.read", "social.approval.status"), actions=("result.record",)),
    ),
)

ACCOUNT = r"^acc_[A-Za-z0-9_-]{8,40}$"
TARGET_OUTCOMES = Literal["succeeded", "failed", "unsupported", "needs_reauth", "app_approval_required", "pending", "unknown_outcome", "cancelled", "skipped"]
RUN_STATES = Literal["queued", "running", "waiting_provider", "reconciling", "succeeded", "partially_succeeded", "failed", "unknown_outcome", "cancelled", "unsupported"]


class TargetsSet(BaseModel):
    account_ids: list[str] = Field(min_length=1, max_length=20)
    providers: list[str] = Field(default_factory=list, max_length=20)


class PlanRecord(BaseModel):
    plan_id: str = Field(pattern=r"^pln_[A-Za-z0-9_-]{8,40}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: str = Field(min_length=3, max_length=64)
    account_ids: list[str] = Field(min_length=1, max_length=20)
    interact_approval_id: str | None = Field(default=None, pattern=r"^apr_[A-Za-z0-9_-]{8,40}$")
    bridge_approval_id: str | None = Field(default=None, pattern=r"^apr_[A-Za-z0-9_-]{8,40}$")


class TargetOutcome(BaseModel):
    account_id: str = Field(pattern=ACCOUNT)
    outcome: TARGET_OUTCOMES
    provider_ref: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    evidence_id: str | None = Field(default=None, max_length=80)


class ResultRecord(BaseModel):
    plan_id: str = Field(pattern=r"^pln_[A-Za-z0-9_-]{8,40}$")
    run_id: str = Field(pattern=r"^run_[A-Za-z0-9_-]{8,40}$")
    run_state: RUN_STATES
    targets: list[TargetOutcome] = Field(min_length=1, max_length=20)


def _check_accounts(ids: list[str]) -> None:
    bad = [a for a in ids if not re.fullmatch(ACCOUNT, a)]
    if bad:
        raise ValidationFailed("account ids must be XN-Interact ids (acc_...)", details={"invalid": bad[:5]})


def set_targets(ctx: Ctx, p: TargetsSet) -> dict[str, Any]:
    _check_accounts(p.account_ids)
    with ctx.bridge.store.tx() as con:
        for a in p.account_ids:
            entities.upsert(con, ctx.workflow_id, "social_target", a, {"account_id": a, "providers": p.providers}, status="SELECTED")
    return {"summary": {"targets": len(p.account_ids)}}


def record_plan(ctx: Ctx, p: PlanRecord) -> dict[str, Any]:
    _check_accounts(p.account_ids)
    with ctx.bridge.store.tx() as con:
        selected = {e["data"]["account_id"] for e in entities.listing(con, ctx.workflow_id, "social_target")}
        missing = [a for a in p.account_ids if a not in selected]
        if missing:
            raise ValidationFailed("plan targets accounts that were not selected in the inspect stage", details={"missing": missing})
        prior = entities.find(con, ctx.workflow_id, "social_plan", p.plan_id)
        if prior is not None and (prior["data"].get("plan_hash") != p.plan_hash or prior["data"].get("account_ids") != p.account_ids):
            raise ValidationFailed("a plan id cannot change its hash or targets; create a new plan")
        entities.upsert(con, ctx.workflow_id, "social_plan", p.plan_id, p.model_dump(), status="PLANNED",
                        merge=lambda old, new: {**old, **{k: v for k, v in new.items() if v is not None}})
    return {"summary": {"plan_id": p.plan_id, "recorded": True, "approvals": {"xn-interact": p.interact_approval_id, "xn-bridge": p.bridge_approval_id}},
            "detail": {"approval_target": f"https://xn-interact.invalid/plans/{p.plan_id}", "action_kind": f"social.{p.operation}"}}


def record_result(ctx: Ctx, p: ResultRecord) -> dict[str, Any]:
    with ctx.bridge.store.tx() as con:
        plan = entities.find(con, ctx.workflow_id, "social_plan", p.plan_id)
        if plan is None:
            raise ValidationFailed("record the plan with plan.record before its result")
        planned = set(plan["data"]["account_ids"])
        unknown = [t.account_id for t in p.targets if t.account_id not in planned]
        if unknown:
            raise ValidationFailed("result names accounts outside the plan", details={"unknown": unknown})
        for t in p.targets:
            if t.evidence_id and not ctx.bridge.evidence.get(t.evidence_id, con):
                raise ValidationFailed(f"unknown evidence {t.evidence_id}")
        status = {"succeeded": "SUCCEEDED", "partially_succeeded": "PARTIAL", "unknown_outcome": "RECONCILIATION_REQUIRED"}.get(p.run_state, p.run_state.upper())
        entities.upsert(con, ctx.workflow_id, "social_result", p.run_id, p.model_dump(), status=status, merge=lambda old, new: new)
        entities.update(con, plan["id"], plan["data"], "EXECUTED")
    counts: dict[str, int] = {}
    for t in p.targets:
        counts[t.outcome] = counts.get(t.outcome, 0) + 1
    return {"summary": {"run_id": p.run_id, "run_state": p.run_state, "targets": counts}}


def actions() -> list[ActionDef]:
    return [
        ActionDef("social", "targets.set", "inspect", "LOCAL_WRITE", set_targets, "record the explicit XN-Interact account ids for this task", TargetsSet),
        ActionDef("social", "plan.record", "act", "LOCAL_WRITE", record_plan, "record an XN-Interact plan id, hash and both approval ids", PlanRecord, safe_when_pending=True),
        ActionDef("social", "result.record", "verify", "LOCAL_WRITE", record_result, "record per-target outcomes of an XN-Interact run", ResultRecord),
    ]
