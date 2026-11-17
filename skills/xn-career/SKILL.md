---
name: xn-career
description: Career intelligence for PKL, internships, graduate and entry-level roles in any region: discover and verify companies and openings, eligibility-first matching, truthful application drafts, supervised submission and tracking. Use when the user asks to find, check, prepare or track an internship or job application.
---

# XN-Bridge career workflow

Required capabilities: web.search, web.fetch, ats.board_read, browser.form_fill, workflow.persist, evidence.store
Optional capabilities: career.listings, document.extract, document.generate, browser.inspect, browser.upload

Use with the `xn-bridge` skill. Start with `workflow_create(domain="career")` and follow `next_action`; it names the single reference to read for the current stage. Actions run through `domain_action(domain="career", action=..., workflow_id=...)`; `action="?"` lists them.

## Stages and actions

| Stage | Actions |
|---|---|
| candidate-profile | profile.ingest, profile.confirm |
| campaign | campaign.define |
| company-discovery | companies.add |
| company-verification | company.verify_domain |
| opportunity-verification | opportunities.fetch_ats, opportunities.ingest, opportunity.reverify |
| matching | match.run |
| application-preparation | application.prepare, draft.check, form.parse_snapshot, form.plan |
| submission | submission.prepare, then approval_prepare |
| tracking | tracking.update, report.pipeline |

## Non-negotiable

- Unknown stays unknown. Never fill a field, claim or eligibility answer the user has not confirmed.
- A listing is OPEN_VERIFIED only through fresh evidence from an official source. A company existing is not a vacancy.
- Hard eligibility checks come before any score. A failed hard check is never hidden by a high score.
- Never solve CAPTCHA, log in for the user, or answer legal, consent or identity declarations for them.
- Submitting needs a human-granted approval bound to the exact payload and target, unless `bridge_status` reports `unattended_external_writes: true`, which only the owner can enable. Then the bridge caps and the stop file apply. Otherwise, if approval cannot be enforced, stop before the final click and let the user press it.
- Existing tools are reused: if `career.listings` resolves, use those tools for listing search instead of scraping.
