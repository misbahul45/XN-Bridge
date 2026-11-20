# Global career trigger

Owner instructions, 2026-11-17: trigger XN-Bridge from the global prompt, then "iya lakukan semua" for the three follow-up steps. Career requests from any directory now reach XN-Bridge through four layers.

## Layers

| Layer | Where | What it does | Enforced by |
|---|---|---|---|
| Core rule | `~/.xninetzy/CORE_PROMPT.md` routing rule 3 (source: `~/code/xninetzy/docs/prompt-injection-core/CORE_PROMPT.md`) | Career work goes to XN-Bridge, not `career_*` or `skill_suggest_for_request`; old rule 3 is now rule 4 and no longer lists career | Model compliance, every CLI |
| Claude adapter | `~/.claude/CLAUDE.md`, block `xn-bridge-trigger:begin`..`end` | Points to rule 3, names the fallback `awaiting input` | Model compliance |
| Hook | `~/.claude/settings.json` `hooks.UserPromptSubmit` runs `scripts/career_trigger_hook.py` | Injects a routing reminder when the prompt has career keywords | Harness |
| Tools | Servers `xn-bridge`, `osm`, `gmaps`, `careers-crawl`, `gmail-send` in Claude Code (user scope), Codex, OpenCode, Cursor, Gemini, Kiro, VS Code and Zed; skill symlinks `xn-bridge` and `xn-career` in `~/.claude/skills`, `~/.codex/skills`, `~/.agents/skills`, `~/.config/opencode/skills` | Makes the bridge tools and skills exist outside this workspace; per-client files, backups and rollback in `docs/mcp-integrations.md` | Each client |

## Verified

- Hook: 30 unit tests pass; piped prompt with "magang" and "Jobstreet" returns the reminder JSON, a non-career prompt returns nothing, exit 0 both times. The hook has not been observed firing in a live prompt; it needs `/hooks` once or a restart to load.
- User-scope servers: all five report Connected from `$HOME`; definitions equal `.mcp.json`; the 20 earlier user-scope servers are unchanged.
- Xninetzy: `validate_prompt_contract.py` source ok, `--installed` 9 of 9 match, governance tests 16 passed (`tests/governance/test_career_routing.py` is new). Repo and installed hashes are equal.
- Not observed: a fresh session actually following rule 3 or the hook reminder.

## Backups and rollback

| Change | Backup | Rollback |
|---|---|---|
| Adapter and core installed | `~/.xninetzy/backups/prompt-v2.3.0-career-20261117T113441Z/` (files, `receipt.json`) | `cp -p <backup>/files/CLAUDE.md ~/.claude/CLAUDE.md` and `cp -p <backup>/files/CORE_PROMPT.md ~/.xninetzy/CORE_PROMPT.md` |
| Xninetzy repo sources | `~/code/xninetzy/docs/prompt-injection-backups/2026-11-17/*.bak` | Restore `CORE_PROMPT.md`, `cli-overrides/claude-CLAUDE.md`, `manifest.json` together; delete `tests/governance/test_career_routing.py` |
| Original adapter before any change | `~/.claude/backups/CLAUDE.md.pre-xn-bridge-trigger` | Only with the repo adapter and manifest restored too, or `--installed` reports drift |
| Hook | `~/.claude/backups/settings.json.pre-career-hook` | Delete the `hooks` key from `~/.claude/settings.json`; restore the file only if nothing else changed since |
| User-scope servers and skills | `~/.claude/backups/claude.json.pre-xn-bridge-user-scope` | `claude mcp remove -s user <name>` for each of the five; `rm ~/.claude/skills/xn-bridge ~/.claude/skills/xn-career` (symlinks only). Do not restore `~/.claude.json` wholesale: Claude Code rewrites it constantly |

The v2.3.0 receipt rollback (`prompt-v2.3.0-20261115T191727Z-5753e6f8`) no longer applies to `CORE_PROMPT.md` and `~/.claude/CLAUDE.md`, because their hashes changed on purpose. Manifest version stays 2.3.0: the validator accepts only 2.2.0 and 2.3.0.

## Limits

- Prompt layers are advice. Caps, stop file and duplicate blocking live in the bridge and in `gmail-send`.
- User-scope settings carry no allow rules for the bridge tools. Outside this workspace every call to them, `gmail_send` included, asks first; inside it the project `.claude/settings.json` allows them. Add allow rules only on a new instruction.
- Codex and OpenCode share the core rule and now have the bridge servers; Cursor, Gemini, Kiro, VS Code and Zed have the servers but not the core rule. None of the hook work was repeated for Codex or OpenCode. Only Codex and OpenCode were checked through their own CLIs; the other five clients were verified by re-parsing their files.
- The hook also fires on the word "glints" in other meanings. That costs one reminder line.
- `docs/evaluation/CONTEXT_COST_RESULTS.json` in the Xninetzy repo holds pre-change hashes and is now historical.
- Another Claude session (`xninetzy-a6`) audits the Xninetzy repo; check `ListAgents` and message it before editing the prompt files again. Nothing in that repo was committed.
- If the Xninetzy installer rewrites `~/.claude/CLAUDE.md` from its source, the source now already carries the shortened block.
