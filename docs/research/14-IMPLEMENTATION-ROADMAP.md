# 14 — Implementation Roadmap (v2)

Verified 2026-11-17. This is a sequence derived from dependencies, not a schedule: no durations are given because none can be defended from the evidence. Nothing here has been implemented in this research pass.

## 1. Automation tiers (decision D-1 for the owner)

| Tier | What runs without per-step prompts | What still needs a person | Prerequisites | Assessment |
|---|---|---|---|---|
| T0 (today) | Nothing special; host prompts apply | Everything external | None | Safe, slow |
| T1 Autonomous research and preparation | All READ and LOCAL_WRITE: search, fetch, ATS reads, evidence capture, CV profile, matching, drafts, tracking, resume | Every email send and every form submit | Allow rules for the mapped read tools; deny list for cost-bearing and destructive tools; skills visible to the host | **Recommended now.** Removes most prompts with no external side effect |
| T2 T1 plus email send | Sending emails that match a batch the person signed once | Browser submits; anything outside the signed batch | Phase 1 enforcement validated; owner-created approver key; Gmail read OAuth; owner decision on a send scope | Reasonable after phases 1 to 3 |
| T3 Everything, including browser submits and unsigned sends | All | Nothing | Not achievable with payload binding on browser clicks (doc 10); third-party terms unchecked (D-3) | **Not recommended.** Conflicts with N-07 and the owner's rules; one injected instruction could send mass applications |

## 2. What installing each tier would change

Each item is a host or system configuration change and needs the owner's approval, a backup, and a rollback note first.

| Change | T1 | T2 | Effect |
|---|---|---|---|
| Keep `xn-bridge` in project `.mcp.json` (current) or add it at user scope in `~/.claude.json` | Yes | Yes | Project scope limits blast radius; user scope makes it available in every project |
| Add `.claude/skills` links to the two project skills | Yes | Yes | Makes `xn-career` and `xn-bridge` discoverable in Claude Code (G-2) |
| Add `permissions.allow` for read tools of mapped capabilities | Yes | Yes | Removes read prompts |
| Add `permissions.deny` for `modal-mcp-server` deploy and remove tools, repository deletion, unreviewed send tools | Yes | Yes | Closes R23 |
| PreToolUse hook script that verifies approvals | No | Yes | Closes R19 for email |
| Managed settings file (needs elevated rights) | Optional | Strongly advised | Prevents the model from editing the rules |
| Gmail send scope, approver key, OAuth | No | Yes (owner actions) | Enables T2 |
| Codex configuration | Unchanged | Equivalent tool filters (Codex honors enabled and disabled tool lists, R8) | Parity |

## 3. Phases

| Phase | Objective | Requirements | Reuse | New components | Dependencies | Technical risks | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| 0 | Owner decisions and prerequisites | D-1, D-2 | Existing CLI | None | Owner time | Skipped backups | Tier chosen; backups of `~/.claude.json`, `~/.claude/settings.json`, `.mcp.json`, Codex config; approver key created by the owner at a terminal | Backup file list; `approver_key_configured: true` |
| 1 | Enforcement spike on a fixture | FR-APR-003, R19, R20, R23 | `tests/fixtures/fake_server.py` | C12 (deny rules, hook) | Phase 0 | Hook cannot read `tool_input` as expected; model can edit rules | Without approval the fixture send is denied; with a signed approval it passes once; replay denied; altered payload denied; denied-tool list blocks a fixture deploy tool | New tests; transcript of denials |
| 2 | Claude Code integration | FR-CAP-001, FR-SKL-001, FR-INT-002 | Existing registry | `.claude/skills` link; host-native search as provider; scoped acceptance (ADR-011) | Phase 0 | Skill description collisions | Real Claude Code session activates `xn-career`; reviewable set equals mapped set; `bridge_status` shows no CHANGED among mapped tools | Session transcript; status output |
| 3 | Live read-path acceptance | FR-DIS-001, FR-OPP-001 to 003, FR-TRK-002 | Search, ATS adapter, Gmail provider | None | Phase 2, Gmail read OAuth | Search provider quality; ATS blocks | One city, 10 companies, verified domains, ATS reads, ownership proof on at least one board; eligibility checked on real postings with source spans; one real mailbox read | Evidence ids; counts |
| 4 | Form assistance on an owner-controlled form | FR-FRM-001, H2 | Playwright | None | Phase 3 | Mapping errors | Form filled to the submit step; no submit; snapshot bytes recorded for `full`, `depth`, `find` | Snapshot sizes |
| 5 | Email tier (T2) | FR-APR-001, ADR-010 | Gmail provider | Send path restricted by hook | Phases 1, 3; owner D-2 | Wrong recipient; daily limits | Batch of 3 messages to the owner's own address; exactly 3 sends; replay and altered body denied; Sent-mail read reconciles | Message ids |
| 6 | Measurement | FR-CTX-001, H1, H3, H4, H5 | Host counters | Harness | Host token counter available | No counter | Matched ten-task comparison across B and C configurations | Token and latency table |

## 4. Smallest vertical slice proving value

One city, ten companies, verified ATS openings, three drafts, one batch approval, hook-gated email to the owner's own address. It exercises phases 1, 3 and 5 without touching an employer.

## 5. What not to start

A gateway, a model router, a dashboard, a vector store, a multi-agent runtime, any unattended browser submission.

## 6. Applied on 2026-11-17: tier T1, project scope only

The owner chose T1, said all MCP servers should be adjusted, and then asked for fully automatic operation. T1 was applied in this project only.

| Change | Detail |
|---|---|
| `.claude/skills/xn-bridge` and `.claude/skills/xn-career` | Relative symlinks to `skills/`; closes G-2 for Claude Code |
| `.claude/settings.json` (new) | permissions allow 19, ask 9, deny 6 |
| Allow | `WebSearch`, `mcp__xn-bridge__*`, web_search search and fetch, markitdown convert, document_generator, Playwright page-reading tools (navigate, snapshot, find, screenshot, console, network, wait, tabs, close, resize), `browser_fill_form`, `browser_select_option` |
| Ask (always prompts; ask outranks allow) | `browser_click`, `browser_type`, `browser_press_key`, `browser_file_upload`, `browser_drag`, `browser_drop`, `browser_handle_dialog`, `browser_evaluate`, `browser_run_code_unsafe` |
| Deny | all `modal-mcp-server` tools; Xninetzy `career_fill_application`, `career_confirm_application`, `career_open_application`, `career_close_application`; `gmail` `send_gmail_message` |

Design choices: `browser_type` asks because it has a `submit` option that presses Enter and would bypass a click gate (W6). `browser_fill_form` has no submit option and is allowed. The Xninetzy deny list is the set the bridge's own `policy.toml` classifies as EXTERNAL_WRITE.

Verification: the file parses; every Playwright tool name exists in the README; no rule appears in two lists. The deny rules took effect live: Claude Code removed the denied Modal and Xninetzy career tools from the session's tool list right after the file was written (VERIFIED_RUNTIME). Allow and ask behavior has not been exercised.

Not changed: `~/.claude.json`, `~/.claude/settings.json`, `~/.codex/config.toml`, `.mcp.json`, `src/`, Xninetzy, data. T1 does not need them, and a user-scope deny would also block Modal and Xninetzy tools in unrelated projects.

Rollback: delete `.claude/settings.json`, `.claude/skills/xn-bridge`, `.claude/skills/xn-career`. The project's `.claude/settings.local.json` was left as it was.

Not installed: T2 and T3. Email sends and form submits still need the person. Unattended sending after one signature needs the owner to create the approver key at a terminal, to decide on a Gmail send scope, and the phase 1 hook to pass its acceptance test.

## 7. Applied on 2026-11-17: unattended external writes in the bridge

After reading the reasons in section 6, the owner explicitly allowed fully autonomous operation. Two changes followed.

**Claude Code rules** (`.claude/settings.json`): `browser_click`, `browser_type`, `browser_press_key`, `browser_file_upload`, `browser_drag`, `browser_drop` and `browser_handle_dialog` moved from ask to allow. Still asking: `browser_evaluate` and `browser_run_code_unsafe`, which run arbitrary script and are not needed to apply. Still denied: Modal tools and the four Xninetzy application tools. The `send_gmail_message` deny was removed; no Gmail provider is registered in Claude Code, so it had no effect.

**Bridge** (source change, owner-enabled):

| Item | Detail |
|---|---|
| Switch | `[autonomy] unattended_external_writes` in `src/xnbridge/defaults/policy.toml`, default false. Enabled for this installation by `data/config/policy.toml` |
| Behavior | `execution_record begin` for an EXTERNAL_WRITE action runs without an approval id when the switch is on. A signed approval still works |
| Rails kept | A target is required; the canonical duplicate guard per workflow, action and target; idempotency; OUTCOME_UNKNOWN after a timeout and no automatic retry; confirmation evidence required for SUBMITTED; audit event `unattended_external_begin` |
| New rails | Daily cap 100 (owner raised it from 25 on 2026-11-17) and per-destination daily cap 5 for unattended starts, counted per UTC day and excluding FAILED; owner stop file `data/STOP_EXTERNAL` blocks new unattended writes immediately; `bridge_status` reports `unattended_external_writes` and `external_writes_stopped` |
| Texts updated | Server instructions, both skills, submission reference, and the `next` hint of `submission.prepare` now describe the unattended path |

Verification: 11 new tests in `tests/security/test_unattended.py` pass: default stays manual, begin without approval, audit event, duplicate blocked under a new key, stop file halts and resumes, daily cap, per-destination cap, unknown outcome not retried, a signed approval still works, success reaches SUBMITTED, success without confirmation stays OUTCOME_UNKNOWN. Full default suite: 337 tests, 0 failures, 0 errors, 6 skipped for needing the real Codex host or installed providers, 132.8 s (VERIFIED_TEST). The unattended path has not run against a live browser or an employer.

Changes take effect for the running server after it restarts, because policy is read at startup.

Rollback and control: set the switch to false or delete `data/config/policy.toml` and restart; `touch data/STOP_EXTERNAL` stops new unattended writes without a restart; remove the file to resume.

Still not possible without the owner: sending email. No Gmail provider with a send scope is registered in Claude Code, and the OAuth consent has to be given by the account holder in a browser.

## 8. Applied on 2026-11-17: free career discovery providers

At the owner's request three providers were added in project scope: OpenStreetMap (`osm`), a local robots-respecting career-page crawler (`careers-crawl`) and a Docker wrapper for `gosom/google-maps-scraper` (`gmaps`). Firecrawl was declined by the owner; the crawler is the free replacement, and Firecrawl self-hosting was rejected on resource grounds (seven services and an open port). Versions, hashes, limits and rollback are in `docs/mcp-integrations.md`. Verification: 39 new unit tests pass offline; one live crawl of a public jobs page returned the title, 60 links and one same-domain email after reading robots.txt; one live Google Maps run returned 20 places in 30.7 s (VERIFIED_RUNTIME). Not done: the Google Places API provider (needs the owner's key and a billing account), Gmail sending (OAuth consent and scope decision), a full catalog discovery under the Claude host.

## 9. Applied on 2026-11-17: Gmail sending through browser-driven OAuth

On the owner's instruction the Gmail authorization was completed with Playwright clicks in the owner's already logged-in browser. The owner personally ticked the Google API Services User Data Policy box; every other step was clicked by the agent: consent screen (External, Testing), test user, Gmail API enablement, Desktop OAuth client, client JSON download into `data/private/` (mode 0600, screenshots that showed the secret deleted), and the consent screen with a single permission. A purpose-built provider (`gmail-send`, scope `gmail.send` only, recipient limited to bridge-verified company domains or an owner list, 100 a day after the owner raised it from 25) replaced the plan to use the upstream Gmail provider, whose cumulative levels would have added modify and compose scopes. One self-test email reached the owner's own address (VERIFIED_RUNTIME: Gmail returned a message id). Remaining: Testing-mode tokens expire after seven days, so authorization must be repeated weekly unless the app is published; no application email has been sent to a company.
