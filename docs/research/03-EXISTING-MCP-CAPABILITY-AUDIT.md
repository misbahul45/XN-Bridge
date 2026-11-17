# 03 — Existing MCP Capability Audit (v2)

Verified 2026-11-17. Counts per server come from the recorded Codex runtime audit (R8, not re-run). Items re-observed in this session are tagged R2, R5, R6.

## 1. Inventory by host

| Host | Registrations | Evidence |
|---|---|---|
| Codex 0.169.0 | 22 including `xn-bridge`, `career-public`, `gmail`; 1,008 tools discovered across 16 initialized local servers; 3 HTTP registrations not probed | R8 runtime audit |
| Claude Code 2.1.326 | 20 user-scope servers (`~/.claude.json`): appium-mcp, canva, codebase-memory-mcp, context7, document_generator, figcraft, figma, github, markitdown, modal-mcp-server, paper_research, playwright, powerpoint, rea, sequential-thinking, web_search, xn-motion, xninetzy, youtube_search, youtube_transcribe. `xn-bridge` is loaded from project `.mcp.json` only. | R5 |
| Reconciliation | The prompt's 1,185 tools and `codex_apps`/`codex_tui` entries match a Codex view. The 177-tool difference from 1,008 is plausibly HTTP servers plus host-injected apps | INFERRED |

The prompt's "one server failed" is not reproduced here: bridge status shows 6 OK, 10 STALE, 3 NOT_PROBED, 1 AUTH_REQUIRED, 1 PERMISSION_DENIED (R2).

## 2. Relevant providers

| Provider | Tools | Availability | Capability and evidence | Risk | Context cost | Reuse |
|---|---:|---|---|---|---|---|
| xn-bridge | 13 | Connected (R2) | State, evidence, approvals, ATS read, career actions (R1, R3) | READ and LOCAL_WRITE; external writes only as bookkeeping | 11,656 B definitions (R3) | Reuse; trim routing (doc 13) |
| xninetzy | 585 (R8) | Initializes; `career_adapter_health` and `career_source_health` return POLICY_HELD approval_channel_unverified in this Claude Code session (R6) | About 45 `career_*` tools plus research, memory, browser, HEBAT, portal | Mixed | Largest single catalog | Reuse only after approval channel is repaired by the owner; never modify |
| playwright | 25 | Metadata verified; browser use held in Codex by a scope prerequisite (R8) | Accessibility snapshots, `browser_find`, `depth` option, `--snapshot-mode full or none`, origin lists that are not a security boundary (W6) | READ for navigation, EXTERNAL_WRITE when clicking submit | Snapshot size dominated | Primary owner of browsing |
| xninetzy browser tools | n/a | `browser_capabilities` returns local Playwright available (R6) | Duplicate of playwright | Mixed | | Fallback only |
| web_search | 6 | Returned zero results with a Bing redirect error (R8) | Search and fetch | READ | Small | Keep, mark degraded |
| host-native WebSearch | 1 | Works in this session (observed) | Search with sources | READ | Host-owned | Not in `capabilities.toml`; add as a provider (gap) |
| career-public | 5 | Installed; one real read; The Muse HTTP 403; 47 substring candidates, not verified internships (R8) | Public job APIs | READ | Small | Reuse as candidate source |
| gmail (workspace-mcp 2.5.0, readonly/core) | 3 read | AUTH_REQUIRED (R2, R8) | Mailbox read for tracking | READ | Small | Reuse; send stays disabled |
| markitdown | 1 | Real PDF extraction passed (R8) | CV extraction | READ | Small | Primary owner of extraction |
| document_generator | 2 | Real PDF generation passed (R8) | Application documents | LOCAL_WRITE | Small | Primary owner of PDF output |
| codebase-memory-mcp | 15 | OK | Code graph | READ | Small | Reuse for code review only |
| modal-mcp-server | 7 | Legacy handshake 2024-11-05 (R8) | Cloud deploy and volumes | EXTERNAL_WRITE with possible cost | Small | Exclude from career workflows; deny in automation mode |
| rea | 207 | Metadata only | Reverse engineering | Dynamic capture and instrumentation | Large | Out of scope for career |
| github | present | Disabled in settings (`disabledMcpjsonServers`) (R5) | Repo operations | EXTERNAL_WRITE | Large | Out of scope |
| paper_research, youtube_*, powerpoint, xn-motion, appium, figma, figcraft, canva, context7, sequential-thinking | various | Metadata only | Unrelated to career | Mixed | Mixed | Out of scope; candidates for non-eager loading |

## 3. Overlap classification

| Responsibility | Candidates | Classification | Recommended primary owner |
|---|---|---|---|
| Web search | host WebSearch, web_search MCP, xninetzy web_search, career-public | Useful fallback plus one degraded provider | Host-native search where present; web_search MCP on hosts without one |
| Page fetch and capture | web_search fetch, xninetzy web_fetch, playwright | Compatible specialization | Fetch for static pages; playwright only when a page needs a browser |
| Browser | playwright, xninetzy browser tools, rea capture | Unnecessary duplication (xninetzy browser, rea) | playwright |
| Document extraction | markitdown, xninetzy document and media tools | Unnecessary duplication | markitdown |
| Durable career state | xn-bridge SQLite, xninetzy `career_track_application` and memory tools | Architectural conflict if both are authoritative | xn-bridge for workflow state; Xninetzy memory for owner knowledge only |
| Career listings | career-public, xninetzy `career_search_*`, bridge ATS adapter | Compatible specialization | ATS adapter for exact boards; career-public for discovery |
| Tool discovery and selection | host tool search, bridge `capability_resolve`, `route_intent` | Duplication risk | Host first; bridge only for provider fallback and health |
| Approval | bridge Ed25519 approvals, Xninetzy HITL tools, host permission prompts | Three mechanisms, none enforced across the host | See doc 10 |

## 4. Integration constraints

1. The Xninetzy policy hold is an owner-side approval channel issue. Routing around it is out of scope (R8).
2. 985 of 1,076 catalogued tool contracts are CHANGED and quarantined (R2). Only 35 are accepted. Per-tool acceptance of the whole catalog does not scale (FR-CAP-003).
3. Protocol versions across servers are mixed: 2024-11-05, 2025-06-18, 2025-11-25, 2026-07-28 (R8). Discovery must negotiate per server.
4. Claude Code does not see the project skills because they are exposed only through `.agents/skills`; there is no `.claude/skills` directory (R5).
5. Greenhouse and Lever application POST endpoints require an employer-held API key (W7, W8). A candidate cannot use them; submission is through the hosted form in a browser.
6. Google Forms has no response-submission method in its official REST reference (W9), so submission is browser-based.
