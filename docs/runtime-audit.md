# Runtime audit — 17 November 2026

Evidence: `bench-out/runtime-audit.json`, `bench-out/discovery-codex.json`, `bench-out/codex-host.json`, `bench-out/capability-acceptance.json`. These are local ignored artifacts. Reproduce with `scripts/runtime_audit.py` and `xnbridge discover --host codex`. Initial workspace code already existed, every project file was untracked, and README/docs were empty. No prior implementation was treated as verified until executed.

## Hardware and runtime

| Finding | Evidence class | Observed value |
|---|---|---|
| OS/kernel | VERIFIED_RUNTIME | Ubuntu 24.04.5 LTS; Linux 6.8.0-149-generic, x86_64 |
| CPU | VERIFIED_RUNTIME | AMD Ryzen 3 5300U, 4 physical cores / 8 logical threads, AVX2 |
| Memory at initial audit | VERIFIED_RUNTIME | 17,829 MiB total; 12,089 MiB available; 2,047 MiB swap, unused |
| Disk at initial audit | VERIFIED_RUNTIME | 192 GiB available on the workspace filesystem |
| GPU | VERIFIED_RUNTIME | AMD Lucienne integrated Radeon; dedicated VRAM/usable inference acceleration UNKNOWN |
| Pressure | VERIFIED_RUNTIME | Initial CPU PSI some avg10 3.10; memory PSI avg10 0; load 4.37/3.96/3.00. These vary. |
| Limits | VERIFIED_RUNTIME | Open files 1,048,576; process limit 70,649 |
| Project runtime | VERIFIED_RUNTIME | Python 3.14.5; SQLite 3.50.4; uv 0.11.16 |
| Libraries | VERIFIED_RUNTIME | MCP 2.3.0; cryptography 50.0.2; pytest 9.2.0; Pydantic 2.14.3 |
| Other runtimes | VERIFIED_RUNTIME | Node 24.16.0; npm 11.18.0; pnpm 11.8.0; Bun 1.4.0; Git 2.43.0 |

The Python/uv project and official SDK were already installed. Initial foundation work added no packages. The later owner-requested MCP integration added two isolated provider environments, documented below; the bridge lockfile and Xninetzy environment are unchanged. No model, database service or orchestration framework was installed. The installed SDK and its [versioned protocol documentation](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/protocol-versions.md) were checked; `auto` and legacy negotiation were exercised.

## Host matrix

| Host | Local evidence | Integration scope |
|---|---|---|
| Codex 0.169.0 | `~/.codex/config.toml`, executable, real app-server calls | VERIFIED_TEST: stdio launch, 13 tools, native project skills, checkpoint/resume. Primary adapter. |
| Claude Code 2.1.325 | `~/.claude.json`, executable, project `.mcp.json` | VERIFIED_CODE configuration adapter; actual Claude-host calls NOT_VERIFIED |
| OpenCode 2.2.6 | executable; `.config/opencode/opencode.json{,c}` | Config/executable detected; adapter NOT_IMPLEMENTED |
| Cursor | executable; `.cursor/mcp.json` | Config detected; adapter NOT_IMPLEMENTED |

Codex exposes paginated MCP status, direct programmatic tool calls, and native skill metadata through its installed app-server API. Its generated local JSON schemas were inspected. Five bridge calls in the acceptance harness require zero inference calls. Deferred tool namespaces and native skill metadata are visible in this interactive host; exact host token savings are UNAVAILABLE. Actual model configuration is `gpt-6.1-sol`, reasoning `xhigh`; no new inference provider was provisioned or invoked by the host test. Approval isolation for sibling external tools is UNKNOWN and therefore not relied on.

## Configured Codex providers

19 sibling registrations were present before adding XN-Bridge. Audit discovered **1,008 tools across 16 successfully initialized local servers**, with three HTTP registrations not probed. Host-injected apps are outside this config count. The older Claude inventory differs and is not merged into the primary catalog.

| Provider | Transport | Negotiated protocol | Tools | Observation |
|---|---|---|---:|---|
| xninetzy | stdio | 2025-11-25 | 585 | Initialize/list works; connected-host search/fetch/scope later POLICY_HELD |
| codebase-memory-mcp | stdio | 2025-11-25 | 15 | Graph discovery reused |
| web_search | stdio | 2025-11-25 | 6 | Search returned zero results; Bing regional redirect error |
| paper_research | stdio | 2025-11-25 | 19 | Metadata only; differs from Claude registration |
| youtube_search | stdio | 2025-11-25 | 10 | Metadata only |
| markitdown | stdio | 2026-07-28 | 1 | Actual local PDF extraction passed |
| playwright | stdio | 2025-11-25 | 25 | Metadata verified; browser execution held by scope prerequisite |
| powerpoint | stdio | 2025-11-25 | 37 | Metadata only |
| document_generator | stdio | 2025-11-25 | 2 | Actual PDF generation passed |
| youtube_transcribe | stdio | 2025-11-25 | 3 | Metadata only |
| sequential-thinking | stdio | 2026-07-28 | 1 | Reasoning tool reused |
| xn-motion | stdio | 2025-11-25 | 39 | Metadata only; isolated startup directory |
| appium-mcp | stdio | 2025-11-25 | 32 | Metadata only |
| rea | stdio | 2026-07-28 | 207 | Metadata only |
| figcraft | stdio | 2025-06-18 | 19 | Metadata only |
| modal-mcp-server | stdio | 2024-11-05 | 7 | Requires legacy handshake; no cloud operations executed |
| figma, context7, canva | HTTP | not negotiated by audit | unknown | Remote host-managed registrations; no new remote server provisioned |

Schemas, descriptions, hashes, versions, annotations and capabilities were collected by local code and stored as catalog artifacts, without injecting full definitions into the model. Rate limits and provider-specific costs are mostly UNKNOWN; configured cost labels are preferences, not measured billing facts. Listing/initialization alone is not operational acceptance. Registry now records the observed Xninetzy permission denial conservatively; it does not modify that dependency's configuration.

After the owner requested installable career/Gmail integrations, two local stdio registrations were added: `career-public` (five host-allowed tools, MCP 2025-11-25) and `gmail` (three read tools, MCP 2026-07-28). Current Codex config has 22 registrations including the bridge; host-injected apps remain outside this count. The initial 1,008-tool snapshot was not relabeled as a complete new catalog scan. Native host sync exercised six selected providers in 4,627 ms, with six inventory calls, 12 startup events and zero model calls. Eight new filtered tool contracts are captured; unrefreshed old providers stay stale/quarantined where appropriate. Gmail initialization succeeded but no account authentication occurred. [Installation sources, versions, licenses and rollback](mcp-integrations.md) record the actual scope.

## Reuse, gaps, and sources

217 readable named skill manifests were found across the native user roots and project, deduplicated by physical path. Plugin/cloud skill catalogs were not exhaustively enumerated. Duplicated descriptions include `exam-qa`/`exam_qa` and the process-engineering aliases. Existing career skills, document tools, browser tools, host permissions, and code graph were retained. Only two thin project coordination skills were exposed, with stage references and no replacement implementations of search, browsers, or document conversion.

Ollama already held `qwen2.5:1.5b` (986 MB on disk) and `gemma3:4b` (3.3 GB). Both were evaluated; the default remains deterministic plus host escalation. Existing Xninetzy memory/harness APIs were inspected/read where accessible, but they are protected external owner state, require verified approval context on relevant operations, and do not provide an enforceable bridge-owned transaction boundary. SQLite inside XN-Bridge is the independent local coordination store; Xninetzy source, schema and configuration were not changed.

None of the named prior research-package Markdown files exists in this workspace. Their contents remain UNKNOWN; the master prompt and runtime evidence drive the implementation. No unsupported historical tool counts or token baselines were adopted.
