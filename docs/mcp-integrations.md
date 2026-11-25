# MCP career integrations — 17 November 2026

XN-Interact's stdio server advertises `data.source.read`, `data.collect`, `data.dataset.query` and `data.dataset.export`. XN-Bridge resolves the local Playwright headless backend through its dynamic router. Use source discovery for authorization and readiness, and register compact dataset references and coverage as evidence. The LinkedIn Jobs and feed routes remain available as legacy tool contracts and require documented platform permission.

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

## Career discovery providers added on 17 November 2026

Registered in project `.mcp.json` first (Claude Code). Backups of the file before each edit are in `data/backups/mcp.json.pre-*`. Later the same day the owner extended registration to user scope and to every other MCP client; see "Registration in every MCP client" at the end of this file.

| Server | What it is | Source, version, license | Boundary |
|---|---|---|---|
| `osm` | OpenStreetMap geocoding and Overpass queries, six read-only tools | `@cyanheads/openstreetmap-mcp-server` 0.7.2, Apache-2.0, npm integrity `sha512-EXOvMHNtteTom2grNvpoz7vr9SgBKnHlnLmWKEjOubQXUiJpyw/pZYHI2mglg1kcrNfGveaRe/pkXbuBtJ1TLQ==`, installed with `--ignore-scripts --save-exact` into `.providers/osm` (37 packages, `package-lock.json`) | No key. Spaces Nominatim calls by 1.05 s. User agent `xn-bridge-career-research/0.1`. Two tools (`reverse_geocode`, `lookup_objects`) are denied to save context; the six definitions total 66,485 bytes |
| `careers-crawl` | Free crawler for company career pages: `crawl_page`, `crawl_site` | Local code, `.providers/crawl/xn_careers_crawl.py`, standard library plus the bridge's own URL safety checks | Obeys robots.txt (unreadable robots means disallow), one request per second per host, one site per crawl, at most 15 pages and depth 2, rejects private addresses, no JavaScript, 1.5 MB page cap. Page text is untrusted |
| `gmaps` | Google Maps business search: `gmaps_search` | Wrapper `.providers/gmaps/xn_gmaps_mcp.py` around `gosom/google-maps-scraper` (MIT), Docker image pinned by digest `sha256:0b9be6be68ad134dd2e9af30e33def1a5f49295965889daec30f0bd111eb9c7d` (2.06 GB, built 2026-11-15) | Fixed command without a shell, 2 GB memory and 2 CPU limit, no published port, input mounted read-only, one run a minute and 20 a day, query validated, only listing fields returned (no user reviews). Scraping Google Maps pages is outside Google's API terms; Google may block it. One live run returned 20 places for `software house Surabaya` in 30.7 s |

Not installed, on the owner's instruction or by evidence: Firecrawl (cloud needs an API key and paid credits; self-hosting runs API, workers, Playwright, Redis, RabbitMQ, PostgreSQL and FoundationDB). The Google Places MCP (`google-maps-places-mcp`) needs a key and a billing account and its repository declares no license file; it can be added if the owner supplies a key.

Bundled defaults: `src/xnbridge/defaults/policy.toml` classifies these tools READ and `src/xnbridge/defaults/capabilities.toml` maps `places.search` and `web.crawl`, so the skill test that checks declared capabilities stays valid. `data/config/policy.toml` now holds only the owner's `[autonomy]` switch. The catalog stores one host fingerprint, so `capability_resolve` reports these providers as HOST_CONFIG_CHANGED until a full `xnbridge discover` runs under the same host. Skills call the tools directly in the meantime.

Rollback: remove the `osm`, `careers-crawl` and `gmaps` entries from `.mcp.json` (or restore the backup), delete the added `osm`, `careers-crawl` and `gmaps` entries from the bundled `[[risk]]` and capability tables, remove the `mcp__osm__*`, `mcp__careers-crawl__*` and `mcp__gmaps__*` rules from `.claude/settings.json`, then `rm -rf .providers/osm .providers/crawl .providers/gmaps` and `docker rmi gosom/google-maps-scraper` and `docker volume rm xn-gmaps-playwright` if desired.

## Email sending: `gmail-send` (17 November 2026)

Own small provider, `.providers/gmail_send/xn_gmail_send.py`, run with the isolated Gmail Python (MCP 2.3.0, `google-auth-oauthlib` 1.5.0, `google-api-python-client` 2.202.0). It exists because the upstream Gmail provider's permission levels are cumulative: its `send` level also requests `gmail.modify` and `gmail.compose`.

| Item | Detail |
|---|---|
| Scope | `https://www.googleapis.com/auth/gmail.send` only. It cannot read, search or change mail |
| Tools | `gmail_send` (EXTERNAL_WRITE in policy), `gmail_send_status` (READ) |
| Recipient rule | One plain address. The domain must be the same site as a company domain marked verified in the bridge database (opened read-only), or the address must be listed in `data/private/gmail-send-allow.txt` |
| Limits | 100 a day, 2 per recipient a day, an identical message is refused for 7 days, stop file `data/STOP_EXTERNAL`, subject one line up to 200 characters, body up to 20,000 characters |
| Attachments | At most 3 files, `.pdf .docx .txt .md`, 5 MB in total, only from `data/outgoing` or `generated_documents` after symlink resolution |
| Evidence | The Gmail message id and thread id returned by the API. A failed or timed-out call is recorded OUTCOME_UNKNOWN and must be reconciled, not retried |
| Secrets | Client file `data/private/gmail-client-secret.json`, token `data/private/gmail-send-token.json` (mode 0600). Both are git-ignored and excluded from bridge backups |
| Authorization | One command, `.providers/gmail/bin/python .providers/gmail_send/xn_gmail_send.py auth`, starts a loopback listener on a random port, prints the consent URL and stores the token on success |

Tests: 26 offline tests in `tests/unit/test_gmail_send.py`. Live verification on 2026-11-17: authorization completed through the browser (consent screen listed one permission, sending email on the owner's behalf; token scope list contains only `gmail.send`, refresh token present), and one self-test email was sent to the owner's own address through the same code path (Gmail message id `1a1e92b7170f7d46`). The `gmail-send` server itself loads in Claude Code after a restart; sending through the MCP tool has not been exercised yet.

Authorization record: Google account `misbahulmuttaqin395@gmail.com` (the account logged in to the Playwright browser), OAuth client `xn-bridge-gmail-send`, Desktop type, one test user. The legal agreement (Google API Services User Data Policy) was accepted by the owner personally; the consent click was made through Playwright on the owner's instruction after the scope list was checked.

Google Cloud setup used: project `focal-dolphin-412812` ("My First Project"), chosen because the account had reached its project limit and this project had no OAuth configuration. External audience, Testing mode. In Testing mode refresh tokens expire after seven days, so the authorization command has to be repeated weekly until the app is published.

## Registration in every MCP client (17 November 2026)

Owner instructions: "iya lakukan semua" (user-scope registration, hook, core routing rule) and then "kamu daftarkan ke semua mcp system". The five servers `xn-bridge`, `osm`, `careers-crawl`, `gmaps` and `gmail-send` use the exact command, args and env of `.mcp.json`, which stays the source of truth. Existing entries were never overwritten; each write was re-parsed and every earlier key compared equal.

| Client | File | Key | Result |
|---|---|---|---|
| Claude Code | `~/.claude.json` (user scope, via `claude mcp add-json -s user`) | `mcpServers` | Five Connected from `$HOME` |
| Codex | `~/.codex/config.toml` | `mcp_servers` | Four tables appended (`xn-bridge` already existed), `startup_timeout_sec = 30`, `tool_timeout_sec = 180`; `codex mcp list` shows all five enabled; 26 servers in total |
| OpenCode | `~/.config/opencode/opencode.jsonc` | `mcp` | Five added; `permission."gmail-send_*" = "ask"` added because OpenCode allows unlisted tools; `opencode mcp list` shows all five connected |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` | Five added |
| Gemini CLI | `~/.gemini/settings.json` | `mcpServers` | Five added |
| Kiro | `~/.kiro/settings/mcp.json` | `mcpServers` | Five added |
| VS Code | `~/.config/Code/User/mcp.json` | `servers` | Five added with `"type": "stdio"` |
| Zed | `~/.config/zed/settings.json` | `context_servers` | Five added |
| Windsurf | no MCP config file exists | none | Not created |

Skills `xn-bridge` and `xn-career` are symlinked into `~/.claude/skills`, `~/.codex/skills`, `~/.agents/skills` and `~/.config/opencode/skills`.

Backups sit next to each file as `<file>.xnb-pre-register-20261117T114255Z`; Claude Code's are `~/.claude/backups/claude.json.pre-xn-bridge-user-scope` and `settings.json.pre-career-hook`. Rollback per client: close its sessions, then either delete the five names (and the OpenCode permission key) or restore that client's backup, which discards later edits to the same file. For Claude Code use `claude mcp remove -s user <name>`; never restore `~/.claude.json` wholesale. Remove the skill symlinks with `rm` on the link only.

Verification and gaps: Codex and OpenCode were checked through their own CLIs (Codex lists the configuration, OpenCode connects). Cursor, Gemini, Kiro, VS Code and Zed were verified only by re-parsing the files; none of those applications was started. `xnbridge discover` was not rerun, so `capability_resolve` can report HOST_CONFIG_CHANGED until a full discover under the Codex host. `xnbridge doctor` reports 0 failed and 2 warnings (approver key not initialised, 985 quarantined schemas); whether either predates this change was not determined. Outside this workspace each client's own approval prompts apply to `gmail_send`; only OpenCode needed an explicit rule.

## xn-interact (social, 2026-11-19)

Bun stdio server in `~/code/XN-Interact`, registered in this repo's `.mcp.json`. 22 tools; 20 `social.*` capabilities in `defaults/capabilities.toml`; 22 exact risk rules plus a fail-closed `xn-interact:*` rule in `defaults/policy.toml`; `social` domain in `domains/social.py`; social intents in `defaults/intents.toml`; host skill `xn-social` linked under `.claude/skills` and `.agents/skills`. Every social write is two-phase and needs the owner's `xn-interact approve <id>` in a terminal in addition to `xnbridge approve`. Rollback and backups: `~/code/XN-Interact/docs/integration/host-registration.md`.
