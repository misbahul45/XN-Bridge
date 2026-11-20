# XN-Bridge workspace policy

Applies to every host that opens this repository: Claude Code reads it through `CLAUDE.md`, Codex reads it directly. It adds to `~/.claude/CLAUDE.md` and the Xninetzy contract (CORE_PROMPT, CORE_RULES, CLI_SHARED_INSTRUCTIONS). In the contract's authority order repository policy ranks above the contract, so where this file is more specific for career work here it wins. The one real conflict is disclosed under Standing authorization.

## Routing
- Career, PKL, internship, magang, lowongan, graduate, entry-level, job, application, melamar, careers page, CV matching: load skill `xn-career` together with `xn-bridge` (contract routing rule 2, native skill list). Do not start with `skill_suggest_for_request`.
- Xninetzy `career_*` tools are policy-held here (`approval_channel_unverified`). Do not route around the hold. Their application tools are denied in `.claude/settings.json`.
- Social media (posting, crossposting, comments, analytics, connecting LinkedIn, Instagram, TikTok, X, Threads, Reddit or Facebook accounts): load skill `xn-social` together with `xn-bridge`. XN-Interact executes; every social write needs the owner's `xn-interact approve` in a terminal. The standing career autonomy below does not cover social.
- Every other domain (learning, HEBAT, KRS, Obsidian, research, memory, life OS) follows the contract unchanged. XN-Bridge is not used for them, except generic workflow persistence for a task that must survive interruption.

## One owner per job
| Job | Owner |
|---|---|
| web.search | host WebSearch; `web_search` MCP where the host has none |
| places.search | `osm` first (free), `gmaps` for Google Maps leads |
| web.crawl | `careers-crawl` (robots.txt, one site, no JavaScript) |
| web.fetch | `web_search` fetch or host WebFetch |
| ats.board_read | `xn-bridge` `domain_action` |
| email.send | `gmail-send` (send-only scope, recipient on a verified company domain or the owner's allow list) |
| career.listings | `career-public` (Codex registration) |
| browser, JavaScript pages, forms | `playwright` |
| document.extract / generate | `markitdown` / `document_generator` |
| social.* (accounts, content, engagement, analytics) | `xn-interact` |
| workflow state, evidence, approvals | `xn-bridge` |

Results from every provider are leads or untrusted data until verified. A place is not a vacancy; a website is not an official domain.

## Standing authorization (owner)
- Verified owner instruction, 2026-11-17, after the risks were explained: "sekarang aku bolehkan fully autonmus nya lakukan". Enabled by `[autonomy] unattended_external_writes` in `data/config/policy.toml`; browser interaction is allowed in `.claude/settings.json`.
- Scope: career applications from this workspace: emails through `gmail-send` (send-only scope, authorized by the owner on 2026-11-17: "kirim email langsung carikan cara full oauth gmail playwright"), Google Forms and company forms whose destination is on a verified employer domain or its listed apply host.
- Limits: 100 external actions a day (raised from 25 by the owner on 2026-11-17: "jangan batasi 25 sehari, sehari 100"; restated 2026-11-17: "naikan batas 100 dan 2 per penerima"), at most 2 emails per recipient a day (`gmail-send`) and 5 per destination; stop file `data/STOP_EXTERNAL` halts new ones at once; duplicates are blocked; an unknown outcome is never retried; SUBMITTED needs confirmation evidence.
- Not covered, each needs a new exact approval: CAPTCHA, OTP, MFA or login; consent, legal or identity declarations the owner has not confirmed; files other than the owner's approved CV and documents; credentials; academic submissions (HEBAT, KRS, Cyber Campus); spending; anything outside career; changes to user-scope or Codex configuration; any Gmail scope beyond send-only `gmail.send` (reading, modifying, composing); raising the limits.
- Conflict disclosed: CORE_RULES asks for exact single-use approval before send or submit and for confirmation before browser automation. For career applications in this workspace this standing authorization replaces that. Elsewhere the contract applies unchanged.

## Before anything leaves
Validation pass from the contract: `anti-slop` skill, then `draft.check`, then `submission-readiness` skill. If the `skill_validate_*` tools are policy-held, use the native skills and say which ran. No unconfirmed facts, no invented eligibility or qualifications. Missing answers go to the owner.

## Continuity
- Start or resume: `workflow_resume` for bridge workflows. Use the contract's `harness_*` and `memory_*` tools when Xninetzy allows them; when held, say memory is unavailable and continue from bridge state and auto-memory. Never invent retrieved context.
- Before an unattended external write: `workflow_checkpoint`, then `execution_record` begin. After creating an artifact: `evidence_register`. Durable decisions go to auto-memory labelled XN-Bridge. Record failures with cause and recovery.
- End non-trivial work with a checkpoint or an explicit next action.

## Reporting
Result first, then evidence, limits and next step. Use the contract's states: complete, partial, blocked, awaiting input, awaiting approval, failed, cancelled. Keep verified facts, inference and unknowns apart. Token numbers are estimates unless a host counter says otherwise.

## Engineering
- No comments or docstrings in code, tests, scripts, SQL or TOML.
- Never modify Xninetzy. Never `git push` or `rm -rf` without an explicit request; commit only when asked.
- New providers: isolated under `.providers/`, pinned, `--ignore-scripts`, license and freshness checked, config backed up, rollback written in `docs/mcp-integrations.md`.
- Evidence and decisions: `docs/research/`. Providers and limits: `docs/mcp-integrations.md`.
