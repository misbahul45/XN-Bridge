# 01 — Executive Architecture Assessment (v2, post-implementation)

Verified 2026-11-17 (Asia/Jakarta). Evidence classes: VERIFIED_RUNTIME, VERIFIED_TEST, VERIFIED_CODE, DOCUMENTED_ONLY, INFERRED, UNKNOWN. Ids R# and W# are in `15-RESEARCH-SOURCES-AND-EVIDENCE.md`. This package supersedes the pre-implementation package in `~/Downloads` (dated 2026-11-17 00:24) where doc 15 section 4 lists corrections.

Research-only: no source, host configuration, Xninetzy file or data was changed. Files were added only under `docs/research/`.

## 1. Situation

The prompt treats XN-Bridge as possibly unbuilt. It is built: 7,784 lines of Python, 13 MCP tools, SQLite state, two skills, installed in the project `.mcp.json` and in Codex (R1, R5). In this session 320 of 326 tests passed and the other 6 were skipped because they need the real Codex host or installed providers (R7). This pass therefore audits the implementation against the original goals instead of predicting it.

## 2. Findings that change decisions

1. **No external-write boundary exists in Claude Code for this user.** No permission rules, no hooks, no approver key (R2, R5). The bridge records approvals but cannot stop a direct tool call; its own documents say so (R8).
2. **Claude Code can enforce one.** Deny, ask, allow rules and PreToolUse hooks can block an MCP tool call before it runs (W2, W3). Nothing is configured.
3. **Skills are invisible to Claude Code.** They are linked only for Codex (R5).
4. **The routing layer is the least justified part.** Held-out accuracy 55 percent on 20 cases, benefit over host tool search unmeasured, and savings are unmeasurable without a host token counter (R8, doc 08).
5. **The largest measured always-on context cost is the skill catalog**, about 17.7 to 23.6 thousand tokens by byte estimate for 231 skills, not the bridge, which costs about 2.9 to 3.9 thousand for 13 tools (R3, R4).
6. **985 of 1,076 tool contracts are quarantined** because acceptance is per tool (R2).
7. **Candidates cannot use Greenhouse or Lever application APIs**; those need the employer's key (W7, W8). Form submission is browser-based, and Google Forms has no official submit method (W9).
8. Xninetzy career tools are policy-held in this host (R6). They cannot own state today.

## 3. Is XN-Bridge necessary?

The core is: durable state, evidence with provenance, payload-bound approvals, and ATS reads. The host provides tool discovery and skill activation. A gateway or multi-agent runtime is not justified. The routing and discovery layer should be treated as optional until measured (docs 04, 13).

## 4. Recommendation

Keep the thin core. Add enforcement at the host, not a gateway. Automate in tiers (doc 14): T1 autonomous research and preparation now; T2 email sending behind signed batches after enforcement is proven; no unattended browser submission.

## 5. What should not be built

A gateway or proxy, a model or embedding router, a multi-agent runtime, a dashboard, a vector store, a scraper for sources that forbid it, anything that modifies Xninetzy.

## 6. Answers to the 40 questions

Tags give the class of the evidence behind each answer.

**Architectural necessity**
1. Separate MCP component? Yes for state, evidence and approvals; no as a router over siblings. (VERIFIED_CODE, INFERRED)
2. Not satisfiable by host plus skills: durable cross-session state, payload-bound approvals, ATS normalization, evidence provenance. (INFERRED from W1, W5)
3. Smallest defensible architecture: two skills, the state and approval core with ATS adapter, host-owned discovery, host-side enforcement. (INFERRED)

**Tool orchestration**
4. Capability discovery: host-native tool search; bridge keeps a local catalog from operator audits. (W4, R8)
5. Routing: the host model selects; the bridge returns provider, fallbacks and degraded text. (VERIFIED_CODE)
6. Coordinating servers: skills plus bridge state; host executes. Programmatic tool calling is optional for read-only batches. (DOCUMENTED_ONLY)
7. Schema change or provider loss: contract hashing and quarantine, cooldown, degraded text; scope acceptance to mapped tools. (VERIFIED_CODE; gap R2)
8. Avoid duplication: one primary owner per responsibility (doc 03 section 3). (INFERRED)

**Skill routing**
9. Discovery and activation: host-native by description; fix Claude Code visibility. (W5, R5)
10. Deterministic, semantic or hybrid: deterministic activation with optional deterministic hints; no model router. (R8, INFERRED)
11. Conditional loading: three levels; 648 B metadata, 2.1 KB bodies, 6.3 KB references. (R4)
12. Dependencies and conflicts: capability names; degraded text; namespaced skill names. (INFERRED)

**Token efficiency**
13. Largest consumer: skill catalog by measured bytes; MCP schemas depend on host deferral and are unmeasured. (R4; UNKNOWN for host)
14. Reduce schema context: host deferral, fewer servers per project, stable lists. (W4, W1)
15. Reduce result context: evidence handles and summaries, deterministic preprocessing. (R8)
16. Programmatic tool calling: batch reads only, never external writes. (DOCUMENTED_ONLY)
17. Browser snapshots: `depth`, `browser_find`, `--snapshot-mode none`; fetch for static pages. (W6)
18. Prompt caching: keep tool lists stable; deterministic ordering is a SHOULD in 2026-07-28. (W1)
19. Verifiable claims today: byte sizes of definitions, skills and instructions; recorded fixture reductions. Not verifiable: any host token saving. (R3, R4)
20. Trade-offs: discovery round trips, sandbox risk, evidence loss from compaction; see doc 08 hypotheses. (INFERRED)

**Career intelligence**
21. CV to profile: extractor text bound to source digest, unknown facts remain unknown, person confirms. (VERIFIED_CODE, R8)
22. Regional discovery: multiple sources with provenance, stated stopping condition, no census claim; search provider currently weak. (R8)
23. Official domain: fresh evidence from that domain; lookalikes unverified. (VERIFIED_CODE)
24. Genuine openings: ATS reads plus employer-domain ownership proof; otherwise LISTED_UNCERTAIN. (R8)
25. Global eligibility: hard constraints from posting text with source spans; remote is not worldwide; accuracy on real postings UNKNOWN. (INFERRED)
26. Matching: hard gates, transparent scores, optional model narrative. (VERIFIED_CODE)
27. Multiple ATS: adapter per documented public board; three exist. (VERIFIED_CODE)
28. Google Forms and custom forms: browser fill by the model, person submits. (W9, doc 10)
29. Email applications: draft from verified facts, recipient from verified domain, send only with signed batch and hook, Gmail send scope undecided. (INFERRED)
30. Tracking: application ids, attempts, confirmation evidence, OUTCOME_UNKNOWN reconciliation. (VERIFIED_TEST on fixtures)

**Security**
31. Independent authorization: every email send and form submit. (doc 10)
32. Direct tool bypass: yes today. (VERIFIED_RUNTIME R5, R8)
33. CV protection: local files 0600, plaintext DB unless disk is encrypted, no upload by the bridge. (R1)
34. Injection and poisoning: untrusted labelling, contract hashing, an enforcement gate outside the model. (W2, R1)
35. Duplicates and uncertainty: single-use approvals, duplicate guard, OUTCOME_UNKNOWN, no retries; cross-campaign duplicates remain a gap. (R8)

**Delivery**
36. Components still to build: host enforcement layer (C12), scoped acceptance, Claude skill visibility, host-native search provider, measurement harness. (doc 05, 14)
37. Reuse unchanged: Playwright, markitdown, document_generator, Gmail provider, host tool search, Xninetzy (untouched). (doc 03)
38. Unnecessary: gateway, model router, dashboard, vector store, multi-agent runtime; the research domain as a shipped surface. (docs 12, 13)
39. Blocked decisions: automation tier, send scope, host token metrics, Xninetzy approval channel, ATS terms. (docs 02, 14)
40. Sequence: phases 0 to 6 in doc 14; smallest slice is one city, ten companies, three drafts, one batch approval, hook-gated email to the owner's own address.

## 7. The request to install full automation

The owner chose tier T1 and asked that all MCP servers be adjusted, then asked for fully automatic operation, and after reading why it was not installed, explicitly allowed it. Installed on 2026-11-17 (doc 14 sections 6 and 7): skills visible to Claude Code; allow, ask and deny rules in project scope; and an owner-enabled unattended mode in the bridge with daily caps, a duplicate guard, an audit trail and a stop file. 337 tests pass with 6 skipped for needing the Codex host or installed providers. Not done: email sending (no Gmail send provider or consent), any live submission, and any change to user-scope or Codex configuration. The posture and residual risks are in doc 10 sections 9 and 10.
