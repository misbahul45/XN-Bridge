# 07 — MCP Capability Routing Design (v2)

Verified 2026-11-17. Sources: W1 (MCP 2026-07-28 changelog), W4 (Claude Code MCP docs), R1, R2, R8.

## 1. Protocol facts

| Fact | Class |
|---|---|
| Revision 2026-07-28 makes MCP stateless (the `initialize` handshake is removed), adds `server/discover` for version, capability and identity, `subscriptions/listen` for opt-in change notifications, Multi Round-Trip Requests replacing server-initiated requests such as `elicitation/create`, `ttlMs` and `cacheScope` result fields, and moves tasks into an extension. Some features are deprecated under a formal lifecycle | DOCUMENTED_ONLY (W1) |
| Live servers negotiate different revisions: 2024-11-05 (modal), 2025-06-18 (figcraft), 2025-11-25 (most), 2026-07-28 (markitdown, sequential-thinking, rea, gmail) | DOCUMENTED_ONLY: recorded runtime audit (R8) |
| Claude Code uses tool search by default; deferral can be disabled or tuned with `ENABLE_TOOL_SEARCH` | DOCUMENTED_ONLY (W4) |
| An MCP server has no access to sibling servers on the host. XN-Bridge's own instructions say it never calls other tools | VERIFIED_CODE (R1) |

## 2. Roles

| Role | Who |
|---|---|
| MCP host | Claude Code or Codex |
| MCP clients | One per connected server, inside the host |
| Capability registry | Bridge C4, populated by an operator audit or Codex inventory, not by live traffic |
| Gateway | Not used |
| Orchestrator | The host model following skills; bridge supplies state and next action |
| Execution broker | None. The host executes; the bridge records |

## 3. Capability-based selection

```text
request -> skill -> required capability ids -> registry lookup
  -> filter: accepted contract, healthy, permitted, offline-compatible
  -> order: declared preference, then cost class, then last-seen health
  -> return provider, fallbacks, degraded text
```

Hard constraints (never traded for convenience): permission denial, AUTH_REQUIRED, quarantined contract, risk class EXTERNAL_WRITE without approval. Soft criteria: cost label (a preference, not billing fact), latency, output size. Deterministic selection is implemented (R1); no model selection exists.

## 4. Behavior under change

| Event | Current behavior (R8, repo docs) | Gap and recommendation |
|---|---|---|
| New server connected | Appears after next operator discovery or Codex inventory sync | Acceptable. Do not accept unmapped tools |
| Server disconnects | Health failures create a cooldown; resolve excludes the failed provider | Fine |
| Tool renamed or schema changed | Hash changes, contract quarantined until accepted | **Scaling gap:** 985 of 1,076 are CHANGED live (R2). Accept per mapped capability only (FR-CAP-003) |
| Invalid output | Recorded; bounded recovery recommendation | Fine |
| Server crash | Same as disconnect | Fine |
| Capability unavailable | `degraded` text from the map | Fine; add host-native WebSearch as a provider |
| Host lacks dynamic discovery | Bounded polling for Codex; no native `tools/list_changed` forwarding assumed | Accept; stale catalog is visible in `bridge_status` (stale true, age 1,726 s, R2) |
| Permission or auth denial | Held; not routed around | Correct. Needs the owner to repair the approval channel |

## 5. Using 2026-07-28 features

- A discovery client built on SDK 2.3.0 negotiates automatically (R8). No change needed for correctness.
- `ttlMs` and `cacheScope` could replace the fixed `catalog_ttl_s` of 21,600 seconds once providers return them. Servers in the audit were not checked for these fields (UNKNOWN).
- `subscriptions/listen` would remove the need for bounded polling on hosts that expose it. The Codex app-server did not expose it (R8).

## 6. Duplicate-functionality control

One primary owner per responsibility (doc 03 section 3). The registry stores fallbacks, so redundancy is explicit and ordered, not accidental.
