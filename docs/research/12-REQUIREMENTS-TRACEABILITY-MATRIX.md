# 12 — Requirements Traceability Matrix (v2)

Verified 2026-11-17. Component ids C1 to C12 are defined in doc 05. ADR ids are in doc 13. Status values come from doc 02.

## 1. Matrix

| Requirement | Need | Component | Decision | Verification | Pri | Status |
|---|---|---|---|---|---|---|
| FR-CAP-001 | N-09 | C9 | ADR-003 | Host inventory vs discovery count | Must | PART |
| FR-CAP-002 | N-07 | C4 | ADR-011 | Mutated-schema fixture | Must | IMPL |
| FR-CAP-003 | N-09 | C4 | ADR-011 | Reviewable set equals mapped set | Should | NONE |
| FR-SKL-001 | N-09 | C8 | ADR-005 | Metadata under 300 est. tokens | Must | IMPL |
| FR-SKL-002 | N-09 | C8, C4 | ADR-005 | Provider removal test | Should | PART |
| FR-SKL-003 | N-09 | none | ADR-004 | Won't | Won't | n/a |
| FR-BRG-001 | N-07 | C1 | ADR-003 | Code search | Must | IMPL |
| FR-BRG-002 | N-09 | C4 | ADR-004 | Fallback fixture | Should | IMPL |
| FR-BRG-003 | N-09 | C5 | ADR-004 | Held-out set | Could | PART |
| FR-CTX-001 | N-09 | Host | ADR-001 | Host token counter | Must | BLOCKED |
| FR-CTX-002 | N-09 | C2 | ADR-005 | Size fixture | Must | IMPL |
| FR-CTX-003 | N-09 | Host | ADR-001 | Counter available | Should | BLOCKED |
| FR-INT-001 | N-10 | X | ADR-002 | Source search | Must | IMPL |
| FR-INT-002 | N-10 | C9 | ADR-008 | Real host smoke tests | Should | PART |
| FR-CAR-001 | N-02 | C6 | ADR-006 | Campaign fixture | Must | IMPL |
| FR-CV-001 | N-06 | C6, C2 | ADR-002 | Conflict fixture | Must | IMPL |
| FR-DIS-001 | N-02 | C6 | ADR-006 | 500-candidate fixture | Must | IMPL fixture |
| FR-DIS-002 | N-03 | C6, C2 | ADR-006 | Lookalike fixture | Must | IMPL |
| FR-OPP-001 | N-04 | C6 | ADR-006 | TTL fixture | Must | IMPL |
| FR-OPP-002 | N-04 | C7 | ADR-006 | Live Ashby read | Must | IMPL |
| FR-OPP-003 | N-05 | C6 | ADR-006 | Constraint fixtures | Must | PART |
| FR-MAT-001 | N-05 | C6 | ADR-006 | Ranking fixture | Must | IMPL |
| FR-FRM-001 | N-06 | C6 | ADR-009 | Snapshot fixture | Should | IMPL |
| FR-FRM-002 | N-06 | C6 | ADR-009 | Unsupported-claim fixture | Must | IMPL |
| FR-APP-001 | N-06 | C6 | ADR-002 | Same fixture | Must | IMPL |
| FR-APR-001 | N-07 | C3 | ADR-007 | Tamper and replay tests | Must | PART |
| FR-APR-002 | N-07 | C3 | ADR-007 | Security tests | Must | IMPL |
| FR-APR-003 | N-07 | C12 | ADR-008, ADR-009, ADR-010 | Denied fixture call | Must | NONE |
| FR-TRK-001 | N-01 | C1 | ADR-012 | Lifecycle fixture | Must | IMPL |
| FR-TRK-002 | N-11 | X (Gmail) | ADR-010 | Mailbox fixture | Should | BLOCKED |
| FR-REC-001 | N-08 | C1, C10 | ADR-012 | SIGKILL cycles | Must | IMPL |
| FR-REC-002 | N-08 | C1 | ADR-007 | Timeout fixture | Must | IMPL |

## 2. Component justification

| Component | Justified by | Note |
|---|---|---|
| C1, C2, C3 | N-01, N-07, N-08 | Core |
| C4 | FR-CAP-002, FR-BRG-002 | Justified for contract hashing and fallbacks |
| C5 | FR-BRG-003 (Could) | **Weakest justification**: no Must requirement needs it |
| C6, C7 | Career Must set | Core |
| C8 | FR-SKL-001 | Core |
| C9 | FR-CAP-001 | Needed only as operator tooling |
| C10 | FR-REC-001 | Reasonable |
| C11 | none in Must set | **Flag**: exists to prove genericity, which the prompt wants without premature generalization. Keep as a test fixture, not a shipped surface |
| C12 | FR-APR-003 | Required, absent |

## 3. Flags

- **Orphan or weak:** C5 and C11 as above.
- **Unverified assumptions:** A-1 (both hosts authoritative), A-2 (public ATS availability), D-3 (third-party terms).
- **Conflicting requirements:** N-07 (authorization for every external write) versus the owner's request to automate everything. They are reconcilable only through pre-approved, payload-bound batches with enforcement outside the model (doc 10). Fully unattended submission conflicts with N-07 and with the owner's standing rules.
- **Must requirements without a passing verification today:** FR-CTX-001, FR-APR-003 (blocked or none). FR-APR-001 and FR-OPP-003 are partial.
- **Requirements without a test method:** none after this matrix.
