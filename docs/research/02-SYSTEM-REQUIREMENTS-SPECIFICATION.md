# 02 — System Requirements Specification (v2, post-implementation)

Verified 2026-11-17 (Asia/Jakarta). Evidence classes: VERIFIED_RUNTIME, VERIFIED_TEST, VERIFIED_CODE, DOCUMENTED_ONLY, INFERRED, UNKNOWN. Source tags R# and W# are defined in `15-RESEARCH-SOURCES-AND-EVIDENCE.md`. Requirement structure follows the ISO/IEC/IEEE 29148:2018 vocabulary as publicly documented; no compliance with the paid standard is claimed.

Status column describes the existing implementation: IMPL (implemented and fixture-tested), PART (partial), NONE, BLOCKED (cannot be verified in the current environment).

## 1. Scope

In scope: a local, stdio, domain-agnostic coordination component plus skills that let an existing MCP host run the career workflow (PKL, internships, graduate and entry-level roles, worldwide) from CV to application tracking, with explicit human control over external actions.

Out of scope: a gateway or proxy over sibling servers, a multi-agent runtime, dashboards, paid services, any change to Xninetzy, credential handling beyond provider-owned OAuth.

## 2. Stakeholders and needs

| Need | Stakeholder | Statement | Evidence | Priority | Uncertainty |
|---|---|---|---|---|---|
| N-01 | Candidate | Application and campaign state survives sessions and hosts | Master prompt 2.2, 12; host memory is conversational (INFERRED) | Must | Low |
| N-02 | Candidate | Coverage-oriented company discovery for a region, with provenance | Master prompt 2.4 | Must | Medium: live search provider currently returns zero results (R8) |
| N-03 | Candidate | Official domain and careers page verified, not guessed | Master prompt 5.1 | Must | Medium |
| N-04 | Candidate | Know which openings are genuinely open vs inquiry-only | Live run kept 5 of 5 Ashby postings LISTED_UNCERTAIN for lack of board-ownership proof (R8) | Must | Medium |
| N-05 | Candidate | Eligibility-first matching against CV facts | Master prompt 12.3, 12.4 | Must | Medium |
| N-06 | Candidate | Truthful, personalized drafts; no invented facts | Master prompt 12.6, 12.7 | Must | Low |
| N-07 | Candidate | Nothing is sent or submitted without my authorization | CORE_RULES (owner), master prompt 13 | Must | High: see FR-APR-003 |
| N-08 | Candidate | No duplicate submissions; recover after interruption | Master prompt 12.8, 14 | Must | Low |
| N-09 | Candidate | Low context overhead on a host with 20+ servers | Master prompt 11; 231 skills, about 1.3 MB of tool definitions (R3, R4, R8) | Should | High: no host token metrics |
| N-10 | Candidate | Zero cost, local-first, CV stays private | Master prompt 1.2 | Must | Low |
| N-11 | Candidate | See replies and outcomes | Master prompt 12.8 | Should | High: Gmail OAuth not granted (R2, R8) |

Secondary stakeholders (employers, platform operators, universities, mail providers) constrain behavior through terms of use and rate limits (W7, W8, W12) but state no requirements of their own to this system.

## 3. Functional requirements

| ID | Requirement | Pri | Need | Verification | Status |
|---|---|---|---|---|---|
| FR-CAP-001 | The system shall identify available MCP capabilities from the selected authorized host or explicitly configured upstream connections | Must | N-09 | Discovery against a fixture server and the real host; compare counts to host inventory | PART: Codex adapter tested (R8); Claude adapter is configuration-level only |
| FR-CAP-002 | The system shall hash each tool contract and quarantine changed contracts until accepted | Must | N-07 | Mutate a fixture schema; assert quarantine | IMPL (R1); live 985 of 1,076 tools CHANGED (R2) |
| FR-CAP-003 | Acceptance shall be required only for tools mapped to a capability, not for the whole catalog | Should | N-09 | Count of tools needing review is bounded by the capability map | NONE |
| FR-SKL-001 | The system shall expose a minimal entry skill with lazy stage references | Must | N-09 | Metadata under 300 tokens; references loaded per stage | IMPL: 648 B metadata (R4); not discoverable by Claude Code (R5) |
| FR-SKL-002 | Skills shall depend on capability names, not tool names | Should | N-09 | Remove a provider; skill still resolves a fallback or reports degraded | PART |
| FR-SKL-003 | A model-based skill router shall not be in the initial scope | Won't | N-09 | Decision record ADR-004 | IMPL (disabled by default) |
| FR-BRG-001 | The bridge shall never execute sibling tools; the host executes and reports results | Must | N-07 | Code search shows no sibling call path outside the operator discovery client | IMPL (R1) |
| FR-BRG-002 | The bridge shall resolve a logical capability to a provider with compatible fallbacks and an explicit degraded behavior | Should | N-09 | Primary failure selects fallback in fixture | IMPL |
| FR-BRG-003 | Intent routing, if kept, shall be deterministic-first with escalation to host reasoning | Could | N-09 | Held-out routing set with confident-error count | PART: held-out accuracy 55 percent on 20 cases (R8) |
| FR-CTX-001 | Where the host permits scoped exposure, irrelevant tool schemas shall not enter model context | Must | N-09 | Host-measured input tokens with and without the bridge | BLOCKED: no host token metrics |
| FR-CTX-002 | Large results shall be stored locally and returned as bounded summaries with handles | Must | N-09 | 243,700-byte fixture returns under 500 bytes | IMPL (R8) |
| FR-CTX-003 | The system shall report tokens measured by an identified method | Should | N-09 | Report names tokenizer or host counter | BLOCKED |
| FR-INT-001 | Browser, search, document, and mail functions shall be reused from existing providers | Must | N-10 | No duplicate implementation in source | IMPL (R1) |
| FR-INT-002 | The design shall work on Claude Code and Codex | Should | N-10 | Real-host smoke test on each | PART: Codex only |
| FR-CAR-001 | A campaign shall define requirements, preferences, geography and a stated coverage and stopping condition | Must | N-02 | Fixture campaign emits bounded queries and a coverage statement | IMPL |
| FR-CV-001 | A profile shall bind every fact to source text; unknown personal facts stay unknown | Must | N-06 | Conflicting CV fixture is flagged | IMPL |
| FR-DIS-001 | Company candidates shall be deduplicated with provenance | Must | N-02 | 500 candidates, 400 added, 100 merged | IMPL on fixtures; live BLOCKED |
| FR-DIS-002 | An official domain shall require fresh evidence captured from that domain | Must | N-03 | Lookalike domain stays unverified | IMPL |
| FR-OPP-001 | Opportunities shall carry a status of OPEN_VERIFIED, LISTED_UNCERTAIN, EXPIRED, INQUIRY_ONLY or UNKNOWN; stale evidence shall not promote status | Must | N-04 | TTL expiry demotes | IMPL |
| FR-OPP-002 | Greenhouse, Lever and Ashby public boards shall be readable as structured data within bounds | Must | N-04 | Live Ashby read of 20 postings | IMPL |
| FR-OPP-003 | Eligibility fields (authorization, citizenship, remote-country list, semester, duration, language, time zone, pay) shall be hard constraints; remote shall not imply worldwide | Must | N-05 | Constraint fixtures | PART |
| FR-MAT-001 | Matching shall report failed or unknown hard constraints before any score | Must | N-05 | Ineligible high-skill posting ranks below eligible | IMPL |
| FR-FRM-001 | Form snapshots shall be classified into field types and user-only declarations | Should | N-06 | Fixture snapshot | IMPL parser; real browser BLOCKED |
| FR-FRM-002 | Missing answers shall be flagged, never fabricated | Must | N-06 | draft.check on unsupported claim | IMPL |
| FR-APP-001 | Drafts shall use only verified candidate facts and captured employer evidence | Must | N-06 | Unsupported-claim fixture | IMPL |
| FR-APR-001 | The architecture shall require independently verifiable user authorization before externally submitting an application | Must | N-07 | Tampered or replayed approval rejected | PART: signature layer IMPL; no approver key exists (R2) |
| FR-APR-002 | Approvals shall be payload-bound, destination-bound, expiring and single-use | Must | N-07 | Security tests | IMPL (VERIFIED_TEST this session if R7 passes) |
| FR-APR-003 | An enforcement boundary outside the model shall deny external-write tools lacking a valid approval | Must | N-07 | A direct call to a fixture send tool without approval is denied | NONE: bridge is bookkeeping only; Claude Code has no permission rules or hooks (R5) |
| FR-TRK-001 | Each submission shall store attempt, destination, confirmation evidence and status history | Must | N-01 | Fixture lifecycle | IMPL |
| FR-TRK-002 | Replies shall be classified from mailbox reads | Should | N-11 | Mailbox fixture | BLOCKED: Gmail AUTH_REQUIRED |
| FR-REC-001 | After interruption, stale attempts shall be recovered and unknown external outcomes flagged | Must | N-08 | 10 SIGKILL cycles | IMPL (R8) |
| FR-REC-002 | External writes shall never be retried automatically | Must | N-08 | Timeout fixture ends OUTCOME_UNKNOWN | IMPL |

## 4. Nonfunctional requirements

Targets marked P are proposed from measured values; they are not guarantees.

| ID | Requirement | Pri | Measure and target | Status |
|---|---|---|---|---|
| NFR-PER-001 | Local state operations stay fast | Must | p95 under 50 ms for lookup, create, checkpoint on the audited laptop (P). Recorded p95: lookup 2.3 ms, checkpoint 8.3 ms, evidence capture 44 ms (R8) | Met in recorded run |
| NFR-PER-002 | Bounded memory | Must | Process RSS under 768 MiB by policy; recorded workload peak 51 MiB (R8) | Met in recorded run |
| NFR-PER-003 | Small tool surface | Should | Bridge tool definitions under 5,000 tokens estimated. Measured 11,656 bytes, about 2.9 to 3.9 thousand tokens by byte estimate (R3) | Met |
| NFR-PER-004 | Small always-on skill metadata | Should | Under 300 tokens for project skills. Measured 648 bytes, about 162 to 216 tokens estimated (R4) | Met |
| NFR-SEC-001 | Least privilege | Must | Gmail registered with three read tools; send absent from capability map | Met (R8) |
| NFR-SEC-002 | Untrusted content never grants permission | Must | Injection fixtures; router vocabulary closed | Met for tested patterns (heuristic) |
| NFR-SEC-003 | Private storage | Must | Directories 0700, keys encrypted, files private | Met (R1) |
| NFR-REL-001 | Crash recovery | Must | 10 of 10 SIGKILL cycles recovered (R8) | Met in recorded run |
| NFR-REL-002 | Concurrent writer integrity | Must | 4 writers, 160 checkpoints, integrity check passes (R8) | Met in recorded run |
| NFR-COM-001 | Protocol compatibility | Must | Stdio; negotiates 2025-11-25 and 2026-07-28 through SDK auto (R8, W1) | Met |
| NFR-COM-002 | Host coverage | Should | Claude Code and Codex | PART |
| NFR-MNT-001 | Small dependency set | Should | Two runtime dependencies (R1) | Met |
| NFR-CST-001 | Zero mandatory cost | Must | No paid API or service; free-tier quotas recorded | Met; Modal and similar servers remain a spend risk if invoked (R5 inventory) |
| NFR-PRV-001 | CV privacy | Must | No upload by bridge; state is plaintext SQLite unless disk encryption exists | PART |
| NFR-OBS-001 | Audit trail | Should | audit and metrics tables | IMPL (R1) |
| NFR-OBS-002 | No unmeasured savings claims | Must | Reports state UNAVAILABLE where host tokens are unknown | Met |

## 5. Interface requirements

- Host to bridge: stdio MCP, protocol negotiated by the SDK; 13 tools with read-only, destructive, idempotent and open-world annotations (R3).
- Human to bridge: `xnbridge approve` on an interactive terminal with an encrypted Ed25519 key (R8). No MCP grant tool exists.
- Bridge to providers: none at runtime; the host executes. An operator CLI audits providers.
- Bridge to public web: a bounded adapter for three ATS hosts only (R1).

## 6. Constraints and dependencies

Xninetzy is read-only. No inbound listeners except the provider's on-demand OAuth loopback callback. No real submissions during research. Host configuration changes need backup and explicit approval. Dependencies that gate acceptance: a working web search provider (R8), Gmail OAuth consent by the owner (R8), an approver key created by the owner (R2), and a deterministic host enforcement mechanism (R5, W2, W3).

## 7. Assumptions and decision dependencies

| ID | Assumption or open decision | Impact if wrong |
|---|---|---|
| A-1 | Claude Code and Codex are both authoritative hosts | Enforcement design differs per host (doc 10) |
| A-2 | Public ATS endpoints stay available and keyless | Adapter degrades to browser capture |
| A-3 | One canonical CV exists on the local disk | Profile versioning handles changes |
| D-1 | Owner decides the automation tier for external writes | Determines FR-APR-003 scope; see doc 14 phase 0 |
| D-2 | Owner decides whether Gmail send scope may ever be enabled | Email automation is impossible without it |
| D-3 | Per-ATS terms of use for automated form filling are unchecked | UNKNOWN; check before any live browser submission |
