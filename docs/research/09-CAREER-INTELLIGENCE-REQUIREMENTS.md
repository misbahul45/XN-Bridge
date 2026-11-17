# 09 — Career Intelligence Requirements (v2)

Verified 2026-11-17. Sources: R1, R8, W7 (Greenhouse), W8 (Lever), W9 (Google Forms), W10 (Gmail), W12 (Overpass). Domain behavior is fixture-verified; live behavior is mostly unverified (R8).

## 1. Lifecycle

| # | Stage | Inputs | Required evidence | Existing tools | Decision rule | Failure modes | State change | Verification |
|---|---|---|---|---|---|---|---|---|
| 1 | Profile ingest | CV file | Extractor text bound to source digest | markitdown, `profile.ingest` | Unconfirmed personal facts stay unknown | Wrong extraction; contact-only edits | profile version | Conflicting CV fixture |
| 2 | Campaign | Categories, geography, constraints | None | `campaign.define` | Requirements separated from preferences; stopping condition stated | Conflicting constraints | campaign | Fixture |
| 3 | Company discovery | Campaign queries | Source and date per candidate | host search, career-public, Overpass optional | Dedup by normalized name and domain | Search returns zero (current state, R8) | company candidates | 500-candidate fixture |
| 4 | Domain verification | Company, domain | Fresh capture from that domain | fetch, browser | Lookalikes stay unverified | Parked or redirected domain | domain status | Lookalike fixture |
| 5 | Careers page research | Verified domain | Page capture | fetch | Careers presence is not a vacancy | JS-only pages | evidence | Fixture |
| 6 | Opportunity ingest | ATS board or page | Capture plus exact board link on the employer domain | ATS adapter, `opportunities.ingest` | OPEN_VERIFIED only with fresh evidence and ownership | Slug collision, stale list | opportunity status | Live Ashby read stayed LISTED_UNCERTAIN (R8) |
| 7 | Eligibility filter | Posting text, profile | Source span per constraint | host model extracts; bridge checks | Unknown stays unknown | Hidden country limits | constraint results | Hard-constraint tests |
| 8 | Matching | Eligible set | Profile facts | `match.run` | Failures reported before scores | Overfit to keywords | ranked list with reasons | Ineligible-ranked-low test |
| 9 | Shortlist | Ranking | None | host | User confirms | | shortlist | Review |
| 10 | Channel analysis | Opportunity | Apply URL | `form.plan` | Classify ATS, form, email | Login wall | channel | Fixture |
| 11 | Preparation | Facts, evidence | Fact pack | `application.prepare`, `draft.check` | No unsupported claim | Hallucinated experience | draft | Unsupported-claim fixture |
| 12 | Document verification | Draft files | Digests | document_generator, markitdown | Re-extract and compare | Render defects | artifacts | Real PDF test (R8) |
| 13 | Form or email prep | Snapshot or recipient | Snapshot, verified address | Playwright, Gmail (read only today) | CAPTCHA, login, sensitive answers go to the person | Mapping errors | prepared manifest | Parser fixture |
| 14 | Human review | Manifest | Full payload shown | `xnbridge approve` | Fail closed if not displayable | Truncated review | review record | Security tests |
| 15 | Authorization | Manifest | Signature | approval service | Payload, destination, single use, expiry | Replays | approval GRANTED | Tamper tests |
| 16 | External submission | Approval | Execution begin record | host tool | No retry on unknown | Timeout | execution | Timeout fixture |
| 17 | Confirmation | Result | Confirmation URL or message id | host | No confirmation means OUTCOME_UNKNOWN | False success | status | Reconcile fixture |
| 18 | Tracking | Events | Evidence | bridge | Duplicate guard per workflow, action, target | Cross-campaign duplicates | application events | Duplicate tests |
| 19 | Follow-up | Replies | Mailbox read | Gmail read (AUTH_REQUIRED) | Eligibility by elapsed time | No mailbox access | follow-up | BLOCKED |
| 20 | Outcome | Reply class | Message evidence | host | Manual classification until mailbox works | | outcome | BLOCKED |

## 2. Company discovery sources

Coverage, not census: the campaign states which sources were queried and why it stopped. Sources by permission:

| Source | Free and permitted | Note |
|---|---|---|
| Host search | Yes | Currently the weakest link: web_search MCP returned zero results (R8) |
| Official company sites | Yes | Domain verification applies |
| University partner lists, industry associations | Yes | Read pages; respect robots and terms |
| OpenStreetMap through Overpass | Yes, subject to usage policy | Public instance asks for under 10,000 queries and 1 GB per day to avoid disturbing others (W12); data license is ODbL (DOCUMENTED_ONLY, license text not re-read) |
| Aggregators (Jobicy, Remotive) | Conditional | Attribution, link back, hourly or daily polling limits (R8); advisory only in this system |
| LinkedIn-style guest scraping | No | Terms restrictions documented in R8; excluded |

## 3. Opportunity status taxonomy

OPEN_VERIFIED requires fresh captured evidence, an exact apply link on the verified employer domain, and no expiry. LISTED_UNCERTAIN: listed but ownership or freshness unproven. INQUIRY_ONLY: no vacancy, a contact route exists. EXPIRED. UNKNOWN. Evidence TTL: listing 3 days, company 30 days, default 7 days (R1).

## 4. Global eligibility fields

Student status, graduation window, work authorization, visa sponsorship, citizenship, allowed countries for remote work, residence requirement, language, time-zone overlap, duration, semester alignment, paid or unpaid, stipend currency. Remote never implies worldwide; a country list that omits Indonesia is a failed hard constraint. Stage 7 depends on the host model reading the posting, so extraction accuracy is UNKNOWN until measured on real postings.

## 5. Matching

Deterministic hard gates first, then a transparent skill and project alignment score, then optional model narrative with mandatory reasons. Weights are labelled preferences, not optimal values. Semantic similarity alone is not accepted. Recorded fixture: 100 matches in 59 ms (R8).

## 6. Channels

| Channel | Submission route for a candidate | Authentication | Confirmation evidence | Automation notes |
|---|---|---|---|---|
| Greenhouse | Hosted form. The POST application endpoint needs the employer's Job Board API key sent as Basic auth, and the docs warn against exposing it (W7) | None for the candidate | Confirmation page | Public job reads are keyless; submission is browser-only |
| Lever | Hosted form. POST needs an account API key; rate limit about 2 applications per second per key (W8) | None for the candidate | Confirmation page or email | Same |
| Ashby, Workday, others | Hosted form | Workday often requires an account | Confirmation page | Account creation is out of scope without owner action |
| Google Forms | No response-submission method in the official REST reference, which offers get and list only (W9) | Sometimes Google sign-in | Form confirmation text | Browser-only |
| Official email | Gmail send (not enabled) | OAuth by owner | Sent message id in Sent mail | Needs `gmail.send` scope decision (D-2); consumer send limits are unverified from an official page (secondary sources say about 500 per day, W10 caveat) |
| University channel | Varies | Varies | Varies | Manual |

## 7. Form assistance rules

Field detection from the accessibility snapshot, classification into text, choice, upload, declaration, and user-only; mapping from verified profile facts only; missing answers listed for the person; conditional and multi-step forms re-inspected after each step; uploads only of approved files; consent declarations never auto-accepted; CAPTCHA and login never bypassed; final submit is a separate authorized action. Real browser behavior is UNVERIFIED (R8).

## 8. Personalization

A draft cites which verified facts and which employer evidence sections it used. Replacing the company name in a generic text fails `draft.check` only when claims are unsupported; stylistic genericity is not detected (limitation).

## 9. Tracking

Application id, workflow id, destination, payload digest, attempt records, confirmation evidence, status history, reply class, follow-up eligibility, reconciliation notes. Cross-campaign duplicates need operator review (R8).
