# 06 — Skill Routing Design (v2)

Verified 2026-11-17. Sources: W5 (Agent Skills specification), R1, R4, R5, R8.

## 1. Facts

| Fact | Class |
|---|---|
| Agent Skills uses progressive disclosure: metadata about 100 tokens, SKILL.md body recommended under 5,000 tokens and 500 lines, detail in separate files; optional `allowed-tools`, `compatibility`, `metadata` fields | DOCUMENTED_ONLY (W5, retrieved 2026-11-17) |
| The host sees 231 skill manifests (deduplicated by real path). Name plus description totals 70,894 bytes, about 17.7 to 23.6 thousand tokens by byte estimate, loaded every session. Full bodies total 1.59 MB | VERIFIED_RUNTIME for sizes (R4); token figures are estimates, not tokenizer output |
| The two project skills total 648 bytes of metadata (about 162 to 216 tokens est.), bodies 2,143 and 2,165 bytes, nine lazy references totalling 6,307 bytes | VERIFIED_RUNTIME (R4) |
| Project skills are linked only under `.agents/skills`. Claude Code reads `~/.claude/skills` and project `.claude/skills`; the latter does not exist. The skill listing of this session does not contain `xn-career` or `xn-bridge` | VERIFIED_RUNTIME (R5) |
| Held-out routing accuracy of the deterministic router is 55 percent on 20 cases with 0 confident errors and 11 escalations; development 92.7 percent on 82 cases. Small local models raised confident errors (6 and 2 on held-out, 11 and 8 on dev) | DOCUMENTED_ONLY: recorded, not re-run (R8) |

Sample size of 20 cannot rank routers; it only shows that rule coverage does not generalize cheaply.

## 2. Routing strategies compared

| Strategy | Cost per request | Correctness evidence | Failure mode | Verdict |
|---|---|---|---|---|
| A Host-native activation by description | Zero extra calls; metadata already loaded | Standard behavior (W5) | Skill not discoverable on the host (true today for Claude Code) | Primary |
| B Explicit intent-to-skill mapping | Zero calls | Brittle | Misses paraphrases | Use only inside a skill |
| C Rule-based routing (bridge `route_intent`) | 0.2 to 0.4 ms (R8) | 92.7 percent dev, 55 percent held-out | Unseen paraphrase becomes escalation, not an error | Optional hint, never authoritative |
| D Semantic retrieval | Embedding model or index | None gathered | Extra infrastructure | Rejected |
| E Hybrid: A for activation, C for stage hints | Low | Combined above | Same | Recommended |
| F Model-based selection | Extra LLM call, 1.2 to 10 s per local call (R8) | Worse confident-error counts than deterministic on this set | Confident wrong routes | Rejected for initial scope |

No evidence here shows a model router beating deterministic selection. The measured result points the other way on confident errors (INFERRED from R8).

## 3. Answers to the routing questions

| Question | Answer |
|---|---|
| One entry skill or several? | Two are enough: a generic coordination skill and a career skill with stage references. Separate activation boundaries for sub-stages are not justified; they cost metadata tokens every session and the stages are sequential |
| Who selects, host or bridge? | Host activates skills. The bridge only returns hints |
| How do skills declare dependencies? | By capability name (`web.search`, `browser.navigate`), resolved at run time. `allowed-tools` should list the bridge tools only, not sibling tools |
| How is activation detected? | Description match by the host. The bridge never observes activation |
| Overlap and priority | Aliases overlap with Xninetzy career skills; leave unchanged; the project skill names are namespaced `xn-` |
| Avoiding irrelevant skills | The larger problem is not these two skills but the other 229. Reducing always-on metadata is a host configuration decision (settings has a `skillOverrides` key; its semantics were not verified) |
| Versioning and cache invalidation | Contract hash in the registry; skill file digest recorded with the workflow; a changed skill digest should be logged, not silently accepted (proposed) |
| Missing required tool | Return `degraded` text from `capabilities.toml`; ask for user input instead of inventing results |
| Host-specific behavior | Codex: native project skills verified. Claude Code: skills not loaded. Fix is a `.claude/skills` link or plugin, which is a host-configuration change needing approval |

## 4. Conceptual skill contract

| Field | Entry skill `xn-bridge` | Career skill `xn-career` |
|---|---|---|
| Identity | name, version, digest | same |
| Intent triggers | multi-step, interruption, external sending | internship, PKL, job, application, melamar |
| Activation condition | host description match | host description match |
| Required capabilities | workflow state | `web.search`, `web.fetch`, `career.listings`, `ats.board_read`, `document.extract` |
| Optional capabilities | `email.read`, `browser.navigate` | same |
| Execution scope | read, local write | read, local write; external write only after approval |
| Permitted side effects | none external | none until approval |
| Required evidence | source reference and captured content for VERIFIED | same |
| Reference loading | by stage | by stage |
| Failure policy | degraded text; ask user | same; never fabricate |
| Output contract | compact structured result and handles | same |

## 5. Decision matrix: where each career responsibility lives

| Responsibility | Location |
|---|---|
| Entry and coordination rules | `xn-bridge` SKILL.md |
| Profile, campaign, discovery, opportunities, verification, matching, application, submission, tracking | `xn-career` references, one per stage, loaded only at that stage |
| Deterministic checks (dedup, TTL, hard constraints, status transitions) | Bridge code, not prose |
| Interpretation and writing | Host model |
