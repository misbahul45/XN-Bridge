# MCP career integrations — 17 November 2026

Two additional local stdio providers are installed and registered in Codex: `career-public` and `gmail`. Existing 20 registrations and all other parsed configuration values were preserved. This extends discovery and prepares read-only mailbox tracking; it does not authorize applications or email sends.

## Discovery scope and selection

The bounded [official registry](https://registry.modelcontextprotocol.io/) search used eight terms: jobs, job-search, internship, career, Gmail, Outlook, calendar, resume. It collected 1,327 version records and 433 distinct server names, including overlaps. The broad jobs query stopped after four pages and has more results. GitHub and an awesome-MCP index supplied additional candidates. This is not an exhaustive inventory of every MCP, and registry publication is not a security endorsement. Raw records: `bench-out/mcp-registry-search.json`.

Priority: local stdio, actual missing capability, compatible runtime, explicit license metadata, inspectable source, small tool surface, public permitted sources, no new paid service or model. Browser/document/memory/orchestration duplicates were excluded. No candidate server was executed during read-only discovery; installation and execution followed as a separate phase under the owner's request.

| Candidate / primary source | License and freshness observation | Decision and boundary |
|---|---|---|
| [mrfentmen public job search](https://github.com/mrfentmen/awesome-servers/tree/main/servers/job-search-mcp) | Package/repository manifest declares MIT; archive contains no separate LICENSE. Repository last commit 2026-11-16; zero stars observed. | **Installed**, moderate evidence. Static source and actual Codex calls checked; five read tools exposed. |
| [Google Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp) | MIT file verified; commit `43b662a938ef002626ac269451c469b91979bd9a`, 2026-11-14; 3,533 stars observed. | **Installed**, strong implementation evidence; Gmail readonly/core only. Account health remains AUTH_REQUIRED. |
| [Neivoc Gmail](https://github.com/Neivoc/gmail-mcp) | MIT; last observed commit 2026-10-26, zero stars | Alternative local Python Gmail provider; fewer maintenance signals; no duplicate installation. |
| [mcp-z Gmail](https://github.com/mcp-z/mcp-gmail) | MIT; observed commit 2026-11-17, five stars | Local stdio possible; documented full-mail scope broader than the selected setup. |
| [floriankuemmel Gmail](https://github.com/floriankuemmel/gmail-mcp) | MIT; observed commit 2026-05-10 | Installer requires macOS Keychain; incompatible with this Ubuntu setup. |
| [Softeria Microsoft 365](https://github.com/Softeria/ms-365-mcp-server) | MIT; observed commit 2026-11-14, 1,144 stars | Viable stdio/read-only alternative for Outlook; owner selected Gmail. |
| [Google Workspace CLI](https://github.com/googleworkspace/cli) | Apache-2.0; observed commit 2026-10-30 | Current source tree has no MCP module; no compatible MCP launch contract verified. Not installed as an MCP. |
| [Servation job search](https://github.com/Servation/job-search-mcp) | MIT; observed commit 2026-08-21 | Duplicates profiles/storage/UI; default LinkedIn guest source has documented usage restrictions. Not selected. |
| [eosphor ATS jobs](https://github.com/eosphor/ats-jobs-mcp) | MIT; observed commit 2026-11-13 | Additional ATS coverage possible; README documents HTTP startup, stdio contract not verified. Existing three ATS adapters retained. |
| [AnshumanAtrey ATS](https://github.com/AnshumanAtrey/ats-jobs-mcp) | MIT declared | Documented hosted remote service; excluded from new local infrastructure. |
| [Open Roles](https://github.com/shanto12/open-roles-mcp), [Hunt](https://github.com/meetshukla/JobSearch-MCP) | Not selected for installation; full license/security acceptance not completed | Cloudflare deployment/storage duplicates the local coordination design. |
| [Jobvision](https://github.com/sepehr071/jobvision-mcp) | MIT documented | Local stdio, Iran-specific; optional regional candidate, no live acceptance performed. |
| [Himalayas](https://github.com/Himalayas-App/himalayas-mcp) | Full installation/license acceptance not completed | Public remote-job source candidate; local transport and relevant write-tool restrictions not verified. Not installed. |

Star counts are discovery observations, not quality scores. None of the dated commits above is over 12 months old. Rows without completed license/security checks are discovery leads, not installation recommendations.

## Installed versions and supply chain

`career-public`: `@mrfentmen/job-search-mcp@1.0.6`, Node 24.16.0, installed with `--ignore-scripts --save-exact --no-fund --no-audit` into `.providers/jobs`. Its transitive lock is `.providers/jobs/package-lock.json` (96 installed packages). Npm archive integrity: `sha512-6b6FnLgu4l8zcvYIl8VetSaT+3Ky/IH6b4v/KnC1/bEYv8xc1G2Bo1W9eO6iIuNvt1J2PrkdCqysfvrjEfSRAQ==`. Published registry metadata still names version 1.0.1 and an older repository URL; the installed server self-reports 1.0.0. These are different observations, not assumed version equivalence. Actual stdio negotiation: 2025-11-25.

`gmail`: `workspace-mcp==2.5.0`, isolated Python 3.14.5 environment `.providers/gmail`, wheel-only installation with 89 resolved packages. Upstream wheel SHA-256: `799e86917ad8d290d348bcffc0f7cbab23965aef2eeaf88355b6af9f6c8eafbf`. Frozen environment: `.providers/gmail/requirements.lock`. Provider reports FastMCP 4.2.0, negotiates MCP 2026-07-28. These dependencies implement an existing Gmail integration; they are not added to the bridge's lockfile or Xninetzy environment. No model, daemon, dashboard or remote deployment was added.

The small launcher `scripts/gmail_stdio.py` reuses upstream code and fixes a verified boundary gap: it adds loopback Host/Origin validation to the on-demand OAuth callback, forces Gmail readonly/core, disables telemetry export and single-user missing-state fallback. Upstream package files are unchanged. Its middleware is exercised without credentials in the installed runtime. No OAuth account grant has been tested.

## Actual acceptance

Codex discovered exactly five public-listing tools and three Gmail read tools. `job_categories` ran through the real host. A direct attempt to invoke disabled `gmail.send_gmail_message` was rejected by Codex before provider execution. This demonstrates that configured operation's boundary; it is not a universal guarantee against shell access or later host reconfiguration.

A bounded `intern` search over Jobicy, Arbeitnow, The Muse and Remotive returned 47 candidates in 1,257.1 ms. The Muse returned HTTP 403 and was reported as unavailable. The first page includes substring false positives, so these are not 47 verified internships or personalized matches. The separate existing fetch provider captured a real employer page. The bridge read 20 Ashby postings, retained five internship-category records, and correctly kept all five LISTED_UNCERTAIN because captured employer evidence lacked an exact board link. No candidate CV, email account or real application was used. Evidence: `bench-out/new-providers-codex.json`, `bench-out/live-career-discovery.json`.

Reuse saved harvest evidence. [Jobicy fair use](https://jobicy.com/jobs-rss-feed) requires source credit/original links and automated passes at least an hour apart. [Remotive's public API](https://github.com/remotive-com/remote-jobs-api) requires attribution and recommends only a few fetches daily. Upstream has no durable rate cache; the skill's polling limits are advisory, and direct host calls can bypass them. No background monitor was scheduled. Do not use default broad/bulk tools as a substitute for these limits.

## Connect Gmail privately

Gmail is registered but **AUTH_REQUIRED**: no OAuth client or account consent was provided. Do not paste credentials into chat. The owner must supply an existing authorized Google OAuth client with Gmail API enabled at:

`/home/misbahul45/code/XN-Bridge/data/private/gmail-client-secret.json` (mode 0600).

The owner can run `.providers/gmail/bin/python scripts/connect_gmail.py --client /absolute/path/client_secret.json`, or use its running desktop wizard described in [OAuth setup](oauth-setup.md). It reuses the provider's OAuth flow, supports account selection in Google's browser, and records health OK only after one successful metadata-only read. The actual account grant and first real mailbox read remain unverified. Use only Gmail readonly scope; changing scopes or enabling sending is a separate decision. No Cloud project, API key or account setting was provisioned automatically. Owner-authorized Playwright scope and the existing OAuth broker were also attempted, but both were held by the existing unverified approval channel.

The upstream OAuth callback starts only on demand on loopback, uses state checks, and stops with its stdio process. A Google browser redirect cannot be delivered over MCP stdin; this is the reason for that limited callback HTTP endpoint. The bridge itself has no HTTP server. Tokens stay in `data/private/gmail-tokens` (private directory); they are not evidence and are excluded from bridge backup archives. Preserve them separately using an owner-controlled encrypted backup if desired.

After the owner actually verifies a mailbox read:

```bash
.venv/bin/python -m xnbridge.cli catalog health --server gmail --status OK --detail 'Owner completed OAuth and verified a read'
```

This records an operator observation; it grants no account or host permission. Until then AUTH_REQUIRED survives metadata refresh and `email.read` degrades safely. Email sending and Gmail draft mutation remain disabled; prepared application messages are local artifacts.

## Operations and rollback

```bash
.venv/bin/python -m xnbridge.cli discover --via-host --only career-public gmail --timeout 45
.venv/bin/python -m xnbridge.cli catalog describe --server career-public --tool search_jobs
XN_RUN_HOST_TESTS=1 .venv/bin/python -m pytest tests/integration/test_career_providers.py
npm ci --prefix .providers/jobs --ignore-scripts --no-fund --no-audit
uv pip install --python .providers/gmail/bin/python --only-binary :all: -r .providers/gmail/requirements.lock
```

Minimal registrations use absolute executables in `~/.codex/config.toml`. Private backup before these two additions: `/home/misbahul45/.codex/config.toml.xnb-career-backup-1794893498493026745`. The exact entries and installation hashes are in `bench-out/provider-install-receipt.json`. To roll back, close affected sessions and remove only `mcp_servers.career-public`, `mcp_servers.gmail`, and its env table. Alternatively compare and restore that backup; restoring the whole file discards later edits. Leave the previous bridge entry and existing integrations intact. No dependency removal is necessary for rollback.
