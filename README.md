# XN-Bridge

A local stdio MCP server for durable workflows, capability selection, evidence, and supervised application preparation. The MCP host executes sibling tools. Career intelligence is the first domain; a research workflow exercises the same coordination core.

Implemented and exercised on Ubuntu with Python 3.14.5, MCP Python SDK 2.3.0 and Codex CLI 0.169.0. No database service, HTTP listener, deployment, telemetry service, or downloaded model is required. Existing Xninetzy source and configuration remain unchanged.

The local core, Codex integration, document providers, full-state recovery, and fixture workflows work. Two additional local providers support public job discovery and read-only Gmail. Actual public search/ATS reads passed; Gmail OAuth and real browser form execution remain incomplete. See [MCP integrations](docs/mcp-integrations.md) and [known limitations](docs/known-limitations.md). No real application or email was sent.

## Run locally

From `/home/misbahul45/code/XN-Bridge`:

```bash
uv lock --check --offline
.venv/bin/python -m xnbridge.cli doctor
.venv/bin/python -m xnbridge.cli status
.venv/bin/python -m xnbridge.cli dry-run career
.venv/bin/python -m xnbridge.cli dry-run career --simulate timeout
.venv/bin/python -m xnbridge.cli dry-run research
```

The existing `.venv` contains all dependencies. On a fresh checkout use `uv sync --locked` (requires access to the existing package cache or package index). Dependencies are the official MCP SDK and cryptography, already present in the lockfile; pytest is development-only.

Codex now has an `xn-bridge` stdio entry in `~/.codex/config.toml`. Start a new Codex session to load it. The executable is `/home/misbahul45/code/XN-Bridge/.venv/bin/python`, arguments `-m xnbridge.server`, with `XN_BRIDGE_HOME=/home/misbahul45/code/XN-Bridge/data`. Run `codex mcp get xn-bridge` to inspect it. For a direct protocol session:

```bash
.venv/bin/python -m xnbridge.server
```

That process waits for MCP input on stdin; stdout carries JSON-RPC only. EOF closes it. There is no background daemon to start or stop. The project `.mcp.json` is also provided for Claude, whose actual host execution has not been tested here.

## Use from the host

Ask the host to use the `xn-bridge` or `xn-career` skill. Codex discovers their project links under `.agents/skills/`. Call `route_intent`, create/resume a workflow, and follow its `next_action`. Resolve capabilities before using sibling tools, record execution attempts/results, register evidence, then checkpoint. `domain_action(domain="career", action="?")` lists the career actions and payload fields without loading every reference.

The server has 13 tools. Approval signing is deliberately absent from MCP. Real external submissions stay manual when the host cannot enforce the boundary. A human can initialize an encrypted local signing key with `xnbridge approval-init` and review an individual pending manifest with `xnbridge approve <id>` in their terminal. Tests use isolated fixture keys; no real approval key was created.

## Discovery and operations

```bash
.venv/bin/python -m xnbridge.cli discover --host codex --out bench-out/discovery-codex.json
.venv/bin/python -m xnbridge.cli discover --via-host --only career-public gmail --timeout 45
.venv/bin/python -m xnbridge.cli discover --via-host --only web_search --watch-seconds 5 --poll-interval 1
.venv/bin/python -m xnbridge.cli catalog status
.venv/bin/python -m xnbridge.cli catalog changed --server web_search
.venv/bin/python -m xnbridge.cli catalog describe --server career-public --tool search_jobs
.venv/bin/python -m xnbridge.cli workflows
.venv/bin/python -m xnbridge.cli workflows <workflow_id>
.venv/bin/python -m xnbridge.cli logs --tail 40
.venv/bin/python -m xnbridge.cli backup
.venv/bin/python -m xnbridge.cli backup --full --out data/backups/private-full.zip
.venv/bin/python -m xnbridge.cli verify-backup data/backups/private-full.zip
.venv/bin/python -m xnbridge.cli restore data/backups/private-full.zip --into bench-out/recovered-home
.venv/bin/python -m xnbridge.cli integrity
```

Default discovery is an operator audit using initialize/tools-list only; stdio providers run serially, HTTP providers are skipped by default, and protected-provider startup data is redirected to bridge scratch storage. `--via-host` uses the installed Codex's own connections without inference. Optional watch is bounded targeted polling plus native startup-event invalidation, not assumed MCP tool-list-change forwarding. Initialization does not prove business permission or account authentication. Authentication/permission holds survive refresh. Changed contracts stay quarantined until reviewed with paginated `catalog changed`, narrow `catalog describe`, and explicit `catalog accept --server <name> --tool <name>`.

Local policy overrides go in `data/config/policy.toml`; capability mappings go in `data/config/capabilities.toml`. Set `[network] offline = true` for bridge-side offline operation, or `XN_BRIDGE_HOST=claude` to select the Claude adapter. The bridge cannot impose offline mode or permissions on tools called directly by the host.

## Tests and measurements

```bash
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m pytest tests/security
XN_RUN_HOST_TESTS=1 XN_RUN_PROVIDER_TESTS=1 .venv/bin/python -m pytest
.venv/bin/python scripts/check_codex_host.py
.venv/bin/python scripts/runtime_audit.py
.venv/bin/python scripts/eval_routing.py
.venv/bin/python scripts/bench_workloads.py --kill-cycles 10
```

The host test starts the installed Codex app-server over stdio, discovers native skills and tools, then exercises checkpoint/resume without an inference turn. The provider test uses installed document servers with synthetic data and offline package launch. Routing evaluation uses only already-installed Ollama models. All submission scenarios use fixtures.

The expanded enabled acceptance suite passes **315 tests**, including real Codex, installed document/public-provider integration and Gmail read-only boundaries. See [test results](docs/test-results.md) for exact runs. Live account/browser limitations are reported separately.

See [runtime audit](docs/runtime-audit.md), [architecture](docs/architecture.md), [career workflow](docs/career-workflow.md), [test results](docs/test-results.md), and [measurements](docs/performance-results.md). State, raw schemas, private documents, logs, and benchmark artifacts are ignored by Git.

## Recovery and registration rollback

`backup --full` creates a private, non-overwriting archive with a consistent SQLite snapshot, every referenced artifact, local config, and any encrypted approval key/public key. Verification checks digests, size/path constraints and database integrity. `restore <archive> --into <new-directory>` publishes a separate validated home and refuses existing destinations. Restored pending/granted approvals are revoked; started external attempts become OUTCOME_UNKNOWN and require reconciliation. Restoring never resubmits anything. Gmail tokens/credentials and host settings are excluded and need their own private backup.

Plain `backup` still creates a database-only snapshot. Preserve referenced artifacts separately when using that legacy mode. Stop all bridge sessions before restoring a database into its existing home; the validated operation retains the preceding database files. Use a new directory for archive restore and inspect its status before changing a host's home path.

Before the Codex addition, a private backup was made at:
`/home/misbahul45/.codex/config.toml.xnb-backup-1794856261494459778`.
To roll back, close bridge sessions and restore that file to `~/.codex/config.toml`, or remove only the `mcp_servers.xn-bridge` table and its env table. Restoring the whole backup also discards later configuration edits, so compare first. Existing 19 server entries and all prior model settings were verified unchanged after registration.

Before adding `career-public` and `gmail`, the separate backup `/home/misbahul45/.codex/config.toml.xnb-career-backup-1794893498493026745` preserved the working 20-server configuration. There are now 22 configured servers. [Integration operations and rollback](docs/mcp-integrations.md) cover these two additions and the owner-only Gmail connection step.

The [local OAuth wizard](docs/oauth-setup.md) is implemented and was launched on the desktop. Run `.providers/gmail/bin/python scripts/connect_gmail.py --check` for readiness, or `--client /absolute/path/client_secret.json` for an owner-supplied Google Desktop client. The account is not connected yet. Despite explicit owner approval, existing Xninetzy scope/OAuth/HITL calls returned `approval_channel_unverified`; Google Console automation through that path remains blocked without changing the protected dependency.
