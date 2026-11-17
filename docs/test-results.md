# Executed tests — 17 November 2026

Baseline before changes: **241 passed in 91.17 s**. The final full command and machine-readable results are:

```bash
XN_RUN_HOST_TESTS=1 XN_RUN_PROVIDER_TESTS=1 .venv/bin/python -m pytest --junitxml=bench-out/final-tests.xml
```

Final result: **268 passed in 101.53 s; zero failures, errors or skips**. Execution details are recorded in `bench-out/final-tests.log` and `bench-out/final-tests.xml`. No real employer endpoint or private candidate document is used. Default test runs skip the explicitly optional host/provider tests unless enabled.

| Acceptance | Executed evidence | Result / scope |
|---|---|---|
| T01 MCP initialization | `tests/integration/test_server_stdio.py` | PASS, actual subprocess stdio |
| T02 discovery | Same; real Codex host test | PASS, 13 tools with schemas/annotations |
| T03 schema compatibility | Same; domain validation tests | PASS, malformed arguments rejected |
| T04 provider replacement | `test_registry_discovery.py` | PASS, primary failure selects compatible fixture fallback |
| T05 missing capability | Registry + host tests | PASS, explicit degraded/offline/removed-provider states |
| T06 deterministic routing | `tests/unit/test_routing.py` | PASS, explicit intents and continuation use no model |
| T07 ambiguity | Same; `scripts/eval_routing.py` | PASS for escalation contract; small-model quality regressions measured |
| T08 skill loading | `test_skills.py`, real Codex `skills/list` | PASS, bounded stage references and native discoverability |
| T09 persistence | MCP restart roundtrip | PASS, checkpoint survives process restart |
| T10 transitions | `test_workflow.py` | PASS, invalid ordering/lifecycle transitions rejected |
| T11 evidence | `test_evidence.py`, profile/security tests | PASS for origin/digest/freshness/ownership rules; not semantic fact verification |
| T12 deduplication | Career discovery/opportunity tests | PASS, company/listing/entity duplicate handling |
| T13 eligibility | `test_career_matching.py` | PASS, failed hard conditions stay separate from scores |
| T14 authorization | `tests/security/test_approval_execution.py` | PASS inside managed bookkeeping; no universal host enforcement claim |
| T15 tampering | Same | PASS, payload/target/signature changes rejected |
| T16 duplicates | Same | PASS, canonical duplicate guard and single-use approvals |
| T17 unknown outcome | Same; timeout dry-run | PASS, OUTCOME_UNKNOWN and no automatic resubmission |
| T18 injection | Security/routing/evidence tests | PASS for tested patterns; heuristic coverage only |
| T19 recovery | Registry/execution tests | PASS, bounded read retries, fallbacks and cooldown |
| T20 context efficiency | `scripts/bench_workloads.py` | Measured raw/summary bytes and progressive references; host token savings unavailable |
| T21 second domain | MCP research e2e; research dry-run | PASS, same generic state/evidence core |
| T22 real host | `tests/integration/test_codex_host.py` | PASS, installed Codex app-server and project skills; zero inference calls |
| T23 local-only | stdio stdout/shutdown/socket tests | PASS, no bridge listening socket or required network/database service |
| T24 bounds | Workflow/registry/resource tests | PASS for deadlines, calls, retries, switches, browser/payload budgets and simulated RSS/memory/CPU-load pressure; no OS CPU quota |

Additional installed-provider test: `test_document_providers.py` uses cached local MCP launchers, generates a synthetic PDF, extracts its text with MarkItDown, binds the exact extraction evidence to a candidate profile, and checks database integrity. Separately generated output was rendered with Poppler and visually inspected; generation/extraction were not inferred merely from tool names.

CLI dry-runs: career success **20/20 checks**, career timeout/reconciliation **22/22**, research **5/5**. Backup/restore tests validate snapshot recovery and reject missing/unrelated/live databases. Multi-process benchmark: four writers, 160 checkpoints, integrity passed. Crash benchmark: ten deliberate child-process SIGKILL cycles, all recovered; only disposable fixture processes were terminated.

Four new security regressions were first run against the old implementation and all failed: altered idempotent request, caller-selected duplicate key, cross-workflow confirmation, and empty/unverified reconciliation statement. All pass after the targeted fixes. A benchmark initially hit the campaign's normal 60-company limit; the benchmark was corrected to request its intended 500-company budget without weakening application limits. One restore test initially expected CREATED instead of the engine's actual PLANNED state; its assertion was corrected. These intermediate failures are not reported as final integration success.

Final privacy regressions also pass: registration previews do not print existing credentials, and catalog summaries remove separate token arguments and URL userinfo/query credentials. Every pre-existing Codex config value was revalidated against the private backup after removing only the new bridge table.

Live limitations: configured web search returned zero results, with a Bing regional-redirect error on one attempt. Xninetzy search/fetch/scope returned policy-held errors. Browser automation was held at the required scope prerequisite. Real browser fill/upload, live opening freshness, real candidate accuracy, employer submission, and post-submit confirmation are therefore **NOT VERIFIED**. No blocked browser test is disguised as a passing fixture or silently counted as a pytest skip.
