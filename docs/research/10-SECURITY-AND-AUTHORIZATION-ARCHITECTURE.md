# 10 — Security and Authorization Architecture (v2)

Verified 2026-11-17. Sources: W2 (hooks), W3 (permissions), W6 (Playwright), W7, W8, W11 (OWASP), R1, R2, R5, R8. This document answers the owner's mid-session request to automate everything: it states which parts can be automated now, which can be after a host boundary exists, and which should stay manual.

## 1. Risk classes

| Class | Examples | Control |
|---|---|---|
| READ | search, fetch, snapshot, ATS read, mailbox read | Host permission prompt or allow rule; untrusted output |
| LOCAL_WRITE | workflow state, evidence, drafts, local PDFs | Allowed; private directories |
| EXTERNAL_WRITE | form submit, email send, account actions, cloud deploy | Per-action authorization bound to payload |

## 2. What the current system actually enforces

| Layer | Enforcement | Class |
|---|---|---|
| Bridge approvals | Signed, expiring, single-use, payload and destination bound, consumed atomically; no MCP grant tool; human CLI needs a TTY and an encrypted key | VERIFIED_CODE and VERIFIED_TEST |
| Bridge as a boundary | None. The host can call any sibling tool directly. The repo's own Codex test demonstrates the bookkeeping bypass | VERIFIED_TEST (R8), stated in repo docs |
| Approver key | Not configured (`approver_key_configured: false`) | VERIFIED_RUNTIME (R2) |
| Claude Code rules and hooks for this user | `~/.claude/settings.json` has no `permissions` block and no `hooks` | VERIFIED_RUNTIME (R5) |
| Codex | Disabled gmail send tool was rejected by the host before execution | DOCUMENTED_ONLY (R8) |
| Xninetzy | `approval_channel_unverified` holds career, search, fetch and scope tools | VERIFIED_RUNTIME (R6) |

Conclusion: today, in Claude Code, nothing outside the model's own judgment stops an external-write call. A request for "fully automating everything" would make that the only control.

## 3. What an enforceable boundary can look like in Claude Code

Facts from the official documentation (W2, W3, retrieved 2026-11-17):

- Permission rules are evaluated deny, then ask, then allow; the first match decides, and a more specific allow cannot carve an exception from a deny.
- A bare tool name or glob deny such as `mcp__server__tool` removes the tool from the model's context.
- PreToolUse hooks can return allow, deny, ask or defer, and can modify tool input. Hook decisions do not bypass deny or ask rules. A hook that exits with code 2 blocks the call before permission rules are evaluated, even if an allow rule exists.
- Administrators can deploy managed settings that user and project settings cannot override.
- MCP tools are matched by the pattern `mcp__<server>__<tool>`.

Design (PROPOSED, not built; INFERRED from the documented mechanics):

1. **Deny list for tools that should never run unattended**: cloud deploy and volume removal (`modal-mcp-server`), repository deletion, any unreviewed send tool.
2. **Hook on email send** (`mcp__gmail__*send*`): the hook computes a digest of recipient, subject, body and attachments from `tool_input`, asks the bridge to verify a granted, unexpired, unconsumed approval for that digest and destination, consumes it, and exits 2 otherwise. This is payload-bound enforcement outside the model.
3. **Browser submission stays human**: a `browser_click` hook sees an element reference and description, not the form payload, so payload binding cannot be enforced. The model fills the form; the person presses Submit. This still automates the research, drafting and form filling.
4. **Where the hook and key live**: outside any path the model may write without prompting. Managed settings are the strongest option because user settings cannot override them; the file location must be confirmed from the docs at install time (not verified here).
5. **Batch approval**: the person reviews a manifest of N emails once and signs once per payload digest; the hook allows exactly those digests, with expiry, per-day cap and per-domain cap, and a revoke command as a kill switch.

Residual risks: a model with unrestricted shell access can edit unmanaged settings or the key directory; same-user local tampering is outside any user-level control (R8). Hook and rule files must be protected by managed settings or file permissions the model cannot change without a prompt.

## 4. Threat table (OWASP Top 10 for Agentic Applications 2026, ASI01 to ASI10, W11)

The primary OWASP page is script-rendered and could not be parsed. ASI01 Agent Goal Hijack and ASI02 Tool Misuse and Exploitation were confirmed from search summaries; other entry titles were not confirmed and are not cited by number.

| Threat | Relevance | Control |
|---|---|---|
| Prompt injection in career pages and form fields | High: pages are the main input | Untrusted data labelling, injection heuristics on evidence, no instruction following from content, EXTERNAL_WRITE gate outside the model |
| Tool poisoning and rug pull | Medium | Contract hashing and quarantine (R1) |
| Overprivileged agent | High under full automation | Deny list, per-tool allow, Gmail readonly scope |
| Credential exposure | Medium | Provider-owned OAuth; Playwright `--secrets` and `--redact-url-params` (W6); tokens excluded from backups |
| Sensitive CV handling | Medium | Local files 0600, DB plaintext; disk encryption is the user's responsibility |
| Replay and duplicates | Medium | Single-use approvals; canonical duplicate guard; no retry on unknown |
| Approval authenticity | High | Signature by a key the model cannot read; TTY requirement; hook verification |
| Browser origin lists | Low reliability | Documented not to be a security boundary (W6) |

## 5. Email trust

Recipients must come from the verified employer domain or a captured careers page. Rate limits, opt-out handling and ambiguous send results (OUTCOME_UNKNOWN until a Sent-mail read confirms) apply. The Gmail provider is read-only and unauthenticated, so reconciliation cannot yet be done. Send scope is a separate owner decision.

## 6. Direct-bypass analysis

| Bypass | Possible today | After proposed controls |
|---|---|---|
| Model calls Gmail send directly | Yes in Claude Code | Denied by hook unless digest approved |
| Model clicks Submit in Playwright | Yes | Still possible; mitigated by prompt on submit-like clicks (`ask` rule on the submit tool path is not specific enough) and the manual final step |
| Model edits settings or keys through shell | Yes unless Bash is restricted | Managed settings; Bash restrictions |
| Injected instruction causes a send | Yes | Same hook; injection cannot create a valid signature |

## 7. Authorization requirements summary

Independent user authorization is needed for every external send or submit (N-07). FR-APR-003 requires a host-side enforcement control and is NONE today. The decision about how much to automate belongs to the owner (D-1, D-2); doc 14 phase 0 lists the options.

## 8. Third-party terms

Whether automated filling of third-party career forms is allowed by each ATS's terms is UNKNOWN (D-3). Greenhouse and Lever expose submission APIs only to employers with keys (W7, W8), which indicates that candidate-side bulk automation is not the intended use. Check terms before any live browser submission.

## 9. Residual risk added after T1 was applied: egress through READ tools

T1 allows page fetch and navigation without prompts. A URL can carry data in its path or query string, so an injected instruction could leak CV or workflow content to an attacker-controlled host using only tools classified as READ. The external-write gate does not cover this, and Playwright's origin lists are documented as not a security boundary (W6). Status: unmitigated in T1 (INFERRED from the documented mechanics, not demonstrated). Proposed mitigation: a PreToolUse hook that allows fetch and navigation only to verified-company and ATS domains and rejects long query strings or embedded credentials; until then, treat fetch and navigate as the trade-off accepted by choosing T1. Browser clicks, typing, key presses and uploads still prompt.

## 10. Posture after unattended mode was enabled (2026-11-17)

The owner removed the per-action human approval for external writes. The authorization model is now: the owner's standing decision, bounded by a daily cap of 25 and 5 per destination, a duplicate guard, confirmation-evidence rules, an audit trail and a stop file. Approvals are no longer payload-bound in this mode, so nothing ties an action to content the person reviewed. An injected instruction on a page can now cause application submissions up to the caps, under the owner's identity, and the bridge cannot tell them from intended ones. Remaining controls outside the model: the two ask rules, the Modal and Xninetzy deny rules, the caps and the stop file. Residual risks R19, R20 and R26 are reduced in blast radius, not closed. The egress risk in section 9 is unchanged.
