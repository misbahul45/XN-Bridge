# 08 — Context and Token Optimization (v2)

Verified 2026-11-17. Tokenizer status: no tokenizer package (`tiktoken` or equivalent) is installed and no Claude tokenizer was available offline. Every token figure below is a **byte-based estimate, bytes divided by 4 to 3**, labelled `est.`. It is not a measured token count. Host-reported input tokens are UNAVAILABLE in this environment.

## 1. Measured baseline

| Item | Size | Est. tokens | Class |
|---|---:|---:|---|
| Global instructions (CLAUDE.md plus three Xninetzy files) | 10,086 B | 2,521 to 3,362 | VERIFIED_RUNTIME size (R4) |
| Skill metadata, 231 skills, name plus description | 70,894 B | 17,723 to 23,631 | VERIFIED_RUNTIME size (R4) |
| Skill bodies if all loaded | 1,585,673 B | 396,418 to 528,557 | VERIFIED_RUNTIME size; not loaded eagerly |
| XN-Bridge project skills metadata | 648 B | 162 to 216 | VERIFIED_RUNTIME size (R4) |
| XN-Bridge 13 tool definitions | 11,656 B | 2,914 to 3,885 | VERIFIED_RUNTIME, measured through stdio in an isolated home (R3) |
| Name, description, input schema of 1,008 Codex tools | 1,296,454 B | 324,114 to 432,151 | DOCUMENTED_ONLY: recorded measurement (R8) |
| Nine compact capability lookups (fixture) | 4,087 B | 1,021 to 1,362 | DOCUMENTED_ONLY (R8) |
| 300-posting board raw vs summary | 243,700 B vs 349 B | n/a | DOCUMENTED_ONLY (R8) |

Answer to "what consumes the most context": by measured size the **skill catalog (about 17.7 to 23.6 thousand tokens est., always on)** exceeds global instructions and the bridge's own tools combined. The 1,008-tool catalog would be an order of magnitude larger if loaded eagerly, but Claude Code defers MCP tools by default through tool search (W4), so its actual cost in this host is UNKNOWN. The answer for the real host requires its token counter.

## 2. What reduces what

| Lever | Targets | Owner | Evidence | Trade-off |
|---|---|---|---|---|
| Host tool search and deferral | Tool-schema context | Host (default on in Claude Code, W4) | DOCUMENTED_ONLY; vendor magnitudes in prior package are third-party and environment-specific | Extra discovery round trip |
| Fewer always-on skills (per-project allowlist) | Skill metadata, the largest measured recurring cost | User configuration (`skillOverrides` key exists, semantics unverified) | Sizes VERIFIED_RUNTIME | Skills must be reachable when needed |
| Lazy stage references | Instruction cost | Project skills | 6.3 KB of references over 9 files vs 4.3 KB of bodies (R4) | None found |
| Evidence handles and bounded summaries | Intermediate results | Bridge | 243,700 B to 349 B (R8) | Raw read costs a second call |
| Deterministic preprocessing (dedup, TTL, constraints, matching) | Intermediate model tokens | Bridge | 500 candidates in 77.8 ms, zero model calls (R8) | Rules need maintenance |
| Programmatic tool calling | Batch loops | Host sandbox, if available | Official best-practice pattern (P); host support UNKNOWN | Sandbox security burden; exclude external-write tools |
| Stable tool list | Prompt-cache hits | Host and servers | DOCUMENTED_ONLY (W1: deterministic ordering SHOULD) | None |

## 3. Playwright

| Fact (W6, retrieved 2026-11-17) | Consequence |
|---|---|
| `--snapshot-mode` accepts `full` or `none`; default `full` | **Correction to the prior package, which cited an "incremental" mode.** The current README documents none. H2 must be tested with `none`, `depth`, and `browser_find` instead |
| `browser_snapshot` has an optional `depth` parameter | Limits tree size |
| `browser_find` searches the accessibility snapshot and returns matches with context | Replaces repeated full snapshots |
| `--caps` adds vision, pdf, devtools only when requested | Keep default minimal |
| `--allowed-origins` and `--blocked-origins` are stated not to be a security boundary and do not affect redirects | Do not rely on them for safety |
| `--redact-url-params`, `--secrets`, `--isolated`, `--storage-state` | Reduce credential exposure |

Static company and ATS pages should use fetch or the ATS adapter, not a browser.

## 4. Hypotheses

| ID | Hypothesis | Metric | Status |
|---|---|---|---|
| H1 | Progressive tool discovery cuts tool-definition context without lowering selection accuracy | Host input tokens, selection accuracy on a fixed task set | BLOCKED: no host token counter |
| H2 | Targeted snapshots (`depth`, `browser_find`, `none`) cut browser-result context versus full snapshots | Bytes and tokens per form-filling task | UNTESTED: browser run blocked by scope prerequisite in Codex; untried in Claude Code |
| H3 | Deterministic preprocessing cuts intermediate model tokens | Model-visible tokens per 100 postings | PART: zero model calls shown for deterministic stages (R8); token comparison not done |
| H4 | Skill progressive disclosure cuts recurring instruction cost | Always-on plus activated tokens | PART: sizes measured; savings versus a monolithic skill not measured |
| H5 | Stable tool interfaces improve cache hits | Cache hit rate | BLOCKED |

## 5. Required metrics for the future experiment

Tool-schema tokens, global instruction tokens, skill metadata and activated skill tokens, intermediate result tokens, total input and output tokens, model round trips, tool call count, task completion, tool selection accuracy, latency, cache hit rate, evidence quality, recovery success. Matched workloads only: the same ten tasks on host-only, skills plus state, and skills plus state plus routing. Target ranges are set after the baseline, not before.

## 6. Claims that cannot be made

No percentage of host token savings. The always-on tool-definition cost of the real host. Prompt-cache behavior. Any benefit of `route_intent` over host skill activation.
