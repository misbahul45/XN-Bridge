# 04 — Architecture Trade-off Analysis (v2)

Verified 2026-11-17. The implementation exists (approximately Architecture C, R1), so this analysis tests the earlier recommendation against evidence rather than predicting it.

## 1. Alternatives

| | A Host-native | B Skills plus minimal state | C Thin bridge (as built) | D Full gateway | E Multi-agent |
|---|---|---|---|---|---|
| Idea | Host composes servers; a skill describes the workflow | A + local state, evidence, approvals | B + capability registry, deterministic routing, discovery tooling | Central proxy mediates all sibling calls | Separate agent runtime with specialists |
| Durable state (N-01, N-08) | No cross-host persistence primitive in MCP (W1, INFERRED) | Yes | Yes | Yes | Needs its own |
| Approval enforcement (N-07) | Host rules only | Bookkeeping only | Bookkeeping only (R1, R8) | Possible for traffic through the gateway; direct host servers bypass it unless removed | Not addressed |
| Context cost | Host-owned | Lowest bridge surface | 13 tools, about 2.9 to 3.9 thousand tokens est. (R3) | Adds a proxy catalog | Highest |
| Added moving parts | None | One server | One server plus operator CLI | Proxy on every call path | Runtime plus agents |
| Maintenance | Lowest | Low | Medium: 7,784 lines of Python (R1) | High | High |

## 2. Mandatory gates (pass or fail)

| Gate | A | B | C | D | E |
|---|---|---|---|---|---|
| Local-first and zero mandatory cost | Pass | Pass | Pass | Pass (open-source options exist, P) | Pass only if local |
| Covers Must needs N-01 and N-08 | Fail | Pass | Pass | Pass | Unproven |
| No unnecessary infrastructure | Pass | Pass | Pass | Fail: no requirement demands a proxy | Fail |
| Honest security claim | Pass | Pass | Pass if documented (it is, R8) | Pass | Unproven |
| Xninetzy unmodified | Pass | Pass | Pass | Pass | Pass |

A fails on durable state. D and E fail the infrastructure gate on present evidence. B and C remain.

## 3. Weighted preferences (ordinal, no numeric weights)

Numeric weights would be arbitrary, so the ratings are ordinal (high, medium, low) and show only direction.

| Preference | B | C |
|---|---|---|
| Requirement coverage | High | High |
| Host compatibility | High | Medium: Codex-verified, Claude config only (R8) |
| Token efficiency | High | High: the extra tools cost about 2 KB (R3), but the benefit is unmeasured |
| Reliability and recovery | High | High |
| Complexity | Low | Medium |
| Reuse of existing systems | High | High |
| Extensibility | Medium | Medium to high |
| Evidence that the extra layer pays off | n/a | Low: held-out routing accuracy 55 percent on 20 cases, 0 confident errors (R8); no host token measurement |

## 4. Verdict

Keep the **state, evidence, approval and ATS core** of C. Treat the **routing and discovery layer** (`route_intent`, `capability_resolve`, discovery CLI) as optional operator tooling, because present evidence does not show it beats host tool search plus skill activation (INFERRED; the measurement that would settle it is BLOCKED by the lack of host token metrics).

Add one thing no alternative currently provides: an enforcement boundary at the host. Claude Code documents deny, ask and allow rules plus PreToolUse hooks that can block an MCP tool call before permission rules run (W2, W3). That is cheaper and more direct than a gateway (D). Detail in doc 10.

## 5. Why not a gateway

A gateway can enforce policy only if sibling servers are reachable solely through it. Doing that removes direct registrations of Playwright and Gmail from the host, breaks host-native tool search over those servers, and adds a proxy on every call. Hooks and permission rules reach the same goal inside the host for Claude Code. Revisit D if a third host appears that has neither hooks nor deny rules.

## 6. Architecture Decision Record summary

Full records are in `13-ARCHITECTURE-DECISIONS.md`. The decisions this analysis supports: ADR-001 (no gateway), ADR-002 (keep the thin core), ADR-004 (routing demoted), ADR-008 (host-level enforcement).
