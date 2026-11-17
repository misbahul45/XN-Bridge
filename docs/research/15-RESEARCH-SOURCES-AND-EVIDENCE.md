# 15 — Research Sources and Evidence Registry (v2)

Date of verification: 2026-11-17 (Asia/Jakarta). Evidence classes: VERIFIED_RUNTIME, VERIFIED_TEST, VERIFIED_CODE, DOCUMENTED_ONLY, INFERRED, UNKNOWN.

## 1. Local evidence

| ID | Evidence | Method | Class |
|---|---|---|---|
| R1 | Source of `src/xnbridge` (7,784 lines of Python plus 392 lines of TOML defaults, 13 MCP tools, 14 SQLite tables plus migrations, two runtime dependencies), `defaults/policy.toml`, `defaults/capabilities.toml` | Read and grep | VERIFIED_CODE |
| R2 | Live `bridge_status` SUMMARY: `approver_key_configured` false; catalog stale; servers AUTH_REQUIRED 1, NOT_PROBED 3, OK 6, PERMISSION_DENIED 1, STALE 10; tools CHANGED 985, OK 35, UNAVAILABLE 56 | One read-only tool call | VERIFIED_RUNTIME |
| R3 | Bridge tool definitions measured through a stdio client against a fresh home in the scratchpad: 13 tools, 11,656 bytes | Script in scratchpad | VERIFIED_RUNTIME |
| R4 | Instruction and skill sizes: global files 10,086 B; 231 skills (deduplicated) 70,894 B metadata, 1,585,673 B bodies; project skills 648 B metadata. Tokens are byte estimates (bytes divided by 4 to 3); no tokenizer available | Python size scan | VERIFIED_RUNTIME for bytes; estimates for tokens |
| R5 | Host configuration structure: Claude Code 2.1.326 with 20 user-scope servers, `xn-bridge` only in project `.mcp.json`, no `permissions` and no `hooks` in `~/.claude/settings.json`, `disabledMcpjsonServers` contains `github`; Codex 0.169.0 registrations; skills linked only in `.agents/skills`, no `.claude/skills`. Only key names were read, no secrets | Read-only parse | VERIFIED_RUNTIME |
| R6 | Xninetzy probes: `career_adapter_health` and `career_source_health` returned POLICY_HELD approval_channel_unverified; `browser_capabilities` returned a local Playwright backend | Three read-only calls | VERIFIED_RUNTIME |
| R7 | Default test run in an isolated process with cache and bytecode disabled: 326 tests, 320 passed, 0 failures, 0 errors, 6 skipped (need `XN_RUN_HOST_TESTS` or `XN_RUN_PROVIDER_TESTS`), 135.1 s. `data/bridge.db` modification time unchanged | pytest with junit output | VERIFIED_TEST |
| R8 | Repo self-reports and artifacts: `docs/*.md`, `bench-out/*`: runtime audit (1,008 tools, 16 servers, negotiated versions), routing evaluation, performance results, live career discovery, integration notes, known limitations. Not re-run | Read | DOCUMENTED_ONLY |

## 2. Primary web sources (retrieved 2026-11-17)

| ID | Source | URL | Facts used | Class |
|---|---|---|---|---|
| W1 | MCP changelog 2026-07-28 | https://modelcontextprotocol.io/specification/2026-07-28/changelog | Stateless core, `server/discover`, `subscriptions/listen`, MRTR, tasks extension, `ttlMs` and `cacheScope`, deprecations | DOCUMENTED_ONLY |
| W2 | Claude Code hooks | https://code.claude.com/docs/en/hooks | PreToolUse decisions allow, deny, ask, defer; exit code 2 blocks; `mcp__<server>__<tool>` matching | DOCUMENTED_ONLY |
| W3 | Claude Code permissions | https://code.claude.com/docs/en/permissions | Deny, ask, allow order; hooks do not bypass rules; blocking hook beats allow; managed settings not overridable; glob deny removes tools from context | DOCUMENTED_ONLY |
| W4 | Claude Code MCP | https://code.claude.com/docs/en/mcp | Tool search is the default; `ENABLE_TOOL_SEARCH`; elicitation modes | DOCUMENTED_ONLY |
| W5 | Agent Skills specification | https://agentskills.io/specification | Metadata about 100 tokens; body under 5,000 tokens and 500 lines; optional `allowed-tools`, `compatibility`, `metadata` | DOCUMENTED_ONLY |
| W6 | Playwright MCP README | https://github.com/microsoft/playwright-mcp (main branch raw README) | `--snapshot-mode full or none`, `depth`, `browser_find`, `--caps`, origin lists not a security boundary, `--secrets`, `--redact-url-params`, `--isolated` | DOCUMENTED_ONLY |
| W7 | Greenhouse Job Board API | https://developers.greenhouse.io/job-board.html | Job reads keyless; application POST requires Basic auth with the Job Board API key, which must stay server-side | DOCUMENTED_ONLY |
| W8 | Lever Postings API | https://github.com/lever/postings-api | Application POST requires an API key from a Super Admin; rate limit on application POSTs | DOCUMENTED_ONLY |
| W9 | Google Forms API `forms.responses` | https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.responses | Reference lists read methods; no submission method found on the page | DOCUMENTED_ONLY |
| W10 | Gmail API quota reference | https://developers.google.com/workspace/gmail/api/reference/quota | API quota units. Consumer daily send limit was **not** confirmed from an official page; secondary sources say about 500 per day | DOCUMENTED_ONLY; send limit UNKNOWN |
| W11 | OWASP Top 10 for Agentic Applications 2026 | https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ | Primary page not parseable; ASI01 Agent Goal Hijack and ASI02 Tool Misuse confirmed from secondary summaries (for example TechRepublic) | DOCUMENTED_ONLY |
| W12 | OSM Overpass API wiki | https://wiki.openstreetmap.org/wiki/Overpass_API | Under 10,000 queries and 1 GB per day is considered non-disruptive on the main instance | DOCUMENTED_ONLY |

## 3. Carried forward from the pre-implementation package

Sources cited in `~/Downloads/01` to `15-*.md` (accessed 2026-11-16) were **not re-verified** here: MCP client best practices, MCP security best practices, OWASP MCP guidance, CSA guidance, Anthropic advanced tool use and programmatic tool calling, Cloudflare Code Mode, FastMCP tool search, gateway landscape, public ATS guides, ISO/IEC/IEEE 29148:2018 and ISO/IEC 25010:2023 (public descriptions only; paid texts not read). Treat them as DOCUMENTED_ONLY, secondary where they were blogs.

## 4. Corrections to the pre-implementation package

1. XN-Bridge source exists and was inspected (it said UNKNOWN).
2. Playwright "incremental snapshot mode" is not in the current README.
3. The "approval mechanism unknown" item is resolved for Claude Code: rules and hooks exist and can block MCP tools; this user has configured none.
4. The "6 focused tools" target became 13 tools, including routing and capability tooling.
5. The 1,185-tool figure is a Codex-view figure; the audit found 1,008 tools on 16 local servers.

## 5. Uncertainties and non-claims

1. No tokenizer was used; all token numbers are byte estimates. No host token consumption was observed.
2. Whether `autoMode` in the user's settings is a deterministic control is UNKNOWN; it was not studied.
3. The managed-settings file path and exact hook input schema for tool arguments must be confirmed from the documentation at install time.
4. Whether any ATS permits automated form filling is UNKNOWN.
5. The held-out routing figure rests on 20 cases.
6. Live career discovery, real browser submission, mailbox reads and email sends are unverified.
7. The six skipped tests need the real Codex host or installed providers and were not run.
8. Nothing in this pass modified source, host configuration, Xninetzy, or data. The only runtime calls were read-only status and health probes, a stdio probe against an isolated home, and the isolated test run.
