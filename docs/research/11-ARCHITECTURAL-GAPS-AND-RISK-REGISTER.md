# 11 — Architectural Gaps and Risk Register (v2)

Verified 2026-11-17. Part A lists defects and gaps observed in this environment. Part B lists hypothetical risks without observed failure. L is likelihood and I is impact (L, M, H). Priority P0 is a precondition for any automation of external writes.

## Part A. Verified gaps

| ID | Gap | Evidence | Class |
|---|---|---|---|
| G-1 | No enforcement boundary for external writes in Claude Code; no approver key exists | `settings.json` has no permissions or hooks (R5); `approver_key_configured: false` (R2) | VERIFIED_RUNTIME |
| G-2 | Skills `xn-bridge` and `xn-career` are invisible to Claude Code | Only `.agents/skills` links exist; session skill list lacks them (R5) | VERIFIED_RUNTIME |
| G-3 | 985 of 1,076 tool contracts are CHANGED and quarantined; catalog stale | `bridge_status` (R2) | VERIFIED_RUNTIME |
| G-4 | Xninetzy `career_*` tools are policy-held in this host | R6 | VERIFIED_RUNTIME |
| G-5 | Live search is unreliable: web_search MCP returned zero results | R8 | DOCUMENTED_ONLY |
| G-6 | Repo documents report 268 tests; the tree now collects 326 (320 passed, 6 env-gated skips, 0 failures in this session) | R7 | VERIFIED_TEST |
| G-7 | Host-native WebSearch is not in `capabilities.toml` | R1, observed | VERIFIED_CODE |
| G-8 | Prior package claimed a Playwright "incremental" snapshot mode; current README documents only `full` and `none` | W6 | DOCUMENTED_ONLY |
| G-9 | Prior package said XN-Bridge source was absent; it is present (7,784 lines of Python, 13 tools) | R1 | VERIFIED_CODE |
| G-10 | Gmail: no OAuth consent; reconciliation of unknown email outcomes impossible | R2, R8 | VERIFIED_RUNTIME |
| G-11 | No host token metrics, so no savings claim is possible | R8 | DOCUMENTED_ONLY |

## Part B. Risk register

| ID | Risk | Evidence basis | L | I | Existing control | Control gap | Mitigation | Pri | Verification |
|---|---|---|---|---|---|---|---|---|---|
| R01 | Bridge duplicates host functions (tool search, skill activation) | `route_intent` and `capability_resolve` overlap; held-out 55 percent on 20 cases (R8); benefit unmeasured | M | M | Router disabled for models; escalation | No comparison against host-only baseline | Feature-flag router; run matched-workload comparison | P2 | Doc 08 H1 |
| R02 | Bridge assumes access to sibling servers | By design it does not (R1); operator discovery starts configured servers | L | M | Isolated scratch dirs; no business calls | Startup of a sibling could have side effects | Allowlist servers for discovery | P3 | Code search plus fixture |
| R03 | Skill routing conflicts with host activation | Only two project skills, distinct descriptions; alias overlap documented (R8) | L | L | Namespaced names | None significant | Keep descriptions distinct | P3 | Skill test |
| R04 | Tool schemas consume excessive context | 1.30 MB for 1,008 tools (R8); host deferral unmeasured | M | H | Host tool search (W4) | No host token data | Measure; scope servers per project | P2 | Doc 08 |
| R05 | Large browser snapshots repeat in context | Documented options exist (W6); never exercised | M | M | `depth`, `browser_find`, `none` available | Not applied in skill | Skill rule: find before snapshot | P2 | H2 |
| R06 | Compaction removes essential evidence | Evidence stored in SQLite with handles (R1) | L | M | Durable store | Model may forget handles | Return handles in checkpoints | P3 | Resume test |
| R07 | Heuristic picks wrong provider | 0 confident errors on 102 recorded cases (R8) | L | M | Closed vocabulary; escalation | Small sample | Expand set from real use | P3 | Routing eval |
| R08 | Stale schemas cause bad calls | G-3 confirmed; host fingerprint changes mark stale | H | M | Quarantine | Review does not scale | FR-CAP-003 | P1 | Count of unreviewed mapped tools equals zero |
| R09 | Overlapping tools give inconsistent results | G-5, G-7: two search providers broken or unmapped | H | M | Fallback order | Working provider not mapped | Add host-native search; record health | P1 | Capability resolve test |
| R10 | Company identity ambiguous | Exact normalized name and domain dedup only (R8) | M | M | Domain verification | Public-suffix handling is lightweight | Add full public-suffix list; user review of ambiguous | P2 | Fixture |
| R11 | Discovery mistaken for a vacancy | Live run kept 5 of 5 LISTED_UNCERTAIN (R8) | L | H | Status taxonomy, ownership proof | Ownership proof unproven live | Capture board link on employer page | P2 | Live read-only run |
| R12 | Remote role rejects candidate's country | Hard constraints modeled | M | H | Unknown stays unknown | Extraction from posting text relies on the model | Require source span; user confirms | P1 | Eligibility fixtures plus real postings |
| R13 | CV parsing adds unsupported qualifications | Evidence-bound profile (R8) | M | H | `draft.check` | No semantic verification (stated in R8) | Human confirmation of profile | P1 | Conflict fixture |
| R14 | Requirements change after research | TTLs 3 and 30 days (R1) | M | M | Reverify demotes | None | Reverify before preparing | P3 | TTL test |
| R15 | Form fields cannot be mapped reliably | Parser tested only on fixtures | M | M | User-only declarations | Real forms untested | Test on a form the owner controls | P2 | Phase 5 |
| R16 | Application submitted twice | Duplicate guard per workflow, action, target (R8) | M | H | Single-use approvals | Cross-campaign duplicates | Global dedupe key over destination and posting | P1 | Duplicate fixture |
| R17 | Browser success without confirmation | OUTCOME_UNKNOWN rule (R8) | M | M | Confirmation evidence required | Evidence authenticity is a host assertion | Capture confirmation page | P2 | Fixture |
| R18 | Email send fails ambiguously | No send path today | M | M | OUTCOME_UNKNOWN, no auto retry | Cannot reconcile without Gmail read | Complete read OAuth first | P1 | Reconcile test |
| R19 | Agent bypasses authorization via direct tool | G-1, Codex test (R8) | H | H | Bookkeeping only | **No boundary** | Hooks and rules (doc 10) | **P0** | Denied fixture call |
| R20 | External content injects instructions | Heuristic detection only (R8) | M | H | Untrusted labelling | Heuristic coverage | EXTERNAL_WRITE gate outside the model | P0 | Injection fixtures plus gate test |
| R21 | Workflow state and browser state diverge | Browser acceptance blocked (R8) | M | M | Checkpoints | Untested | Re-inspect before each action | P2 | Phase 5 |
| R22 | Unnecessary infrastructure or supply chain | Two provider environments: 96 npm packages and 89 Python packages; one provider repo has zero stars and no standalone LICENSE file (R8) | M | M | Pinned versions, `--ignore-scripts`, integrity hashes | Ongoing patching | Review before upgrade; remove if unused | P2 | Dependency audit |
| R23 | Free service causes unexpected charges | Modal MCP can deploy cloud apps (R8 inventory) | L | H | None in bridge | Nothing prevents a model call | Deny list for cost-bearing tools | P0 | Denied fixture call |
| R24 | Host lacks the discovery pattern | Claude adapter is configuration-level only (R8) | M | M | Operator CLI | No Claude host test | Real Claude Code smoke test | P2 | Phase 2 |
| R25 | Claimed token reduction is not real | Reports mark UNAVAILABLE (R8) | M | M | Explicit non-claims | No metric | Host counter before any claim | P2 | Doc 08 |
| R26 | Full automation amplifies R19, R20, R23 | Unattended execution removes the last human check | H | H | None | Entire boundary missing | Tiered automation (doc 14) | P0 | Phase 1 acceptance |
